import hashlib
import re
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine import MaineScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maine_section import (
    parse_maine_section_html,
    source_bound_maine_chapter_disposition,
    source_bound_maine_section_disposition,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
)

ROOT_URL = "https://legislature.maine.gov/statutes/"
TITLE_URL = "https://legislature.maine.gov/statutes/1/title1ch0sec0.html"
CHAPTER_URL = "https://legislature.maine.gov/statutes/1/title1ch1sec0.html"
SECTION_URLS = [
    "https://legislature.maine.gov/statutes/1/title1sec1.html",
    "https://legislature.maine.gov/statutes/1/title1sec2.html",
]
TITLE_2_URL = "https://legislature.maine.gov/statutes/2/title2ch0sec0.html"
CHAPTER_2_URL = "https://legislature.maine.gov/statutes/2/title2ch1sec0.html"
SECTION_2_URL = "https://legislature.maine.gov/statutes/2/title2sec1.html"
TITLE_22_URL = "https://legislature.maine.gov/statutes/22/title22ch0sec0.html"
ACTIVE_CHAPTER_22_URL = (
    "https://legislature.maine.gov/statutes/22/title22ch564sec0.html"
)
TERMINAL_CHAPTER_CASES = (
    (
        "https://legislature.maine.gov/statutes/22/title22ch565sec0.html",
        "Chapter 565: GENETICALLY ENGINEERED PRODUCTS REVISOR'S NOTE: PUBLIC "
        "LAW 2013, CHAPTER 436, SECTION 2 CONTAINED A CONTINGENT EFFECTIVE DATE "
        "AND A CONTINGENT REPEAL. BECAUSE CERTIFICATION WAS NOT RECEIVED BEFORE "
        "JANUARY 1, 2018, AS REQUIRED BY THE CONTINGENCY, THE ACT WAS REPEALED "
        "ON JANUARY 1, 2018, AND TITLE 22, CHAPTER 565 NEVER TOOK EFFECT.",
        "Title 22, Chapter 565: GENETICALLY ENGINEERED PRODUCTS",
        "never_effective_chapter",
    ),
    (
        "https://legislature.maine.gov/statutes/22/title22ch1081sec0.html",
        "Chapter 1081: MAINE CHILDREN'S TRUST FUND CONSISTING OF SECTIONS 4081 "
        "TO 4086 REPEALED",
        "Title 22, Chapter 1081: MAINE CHILDREN'S TRUST FUND",
        "repealed_chapter",
    ),
)


def _discovery_pages() -> dict[str, bytes]:
    return {
        ROOT_URL: b"<html><body><a href='1/title1ch0sec0.html'>TITLE 1</a></body></html>",
        TITLE_URL: b"<html><body><a href='./title1ch1sec0.html'>Chapter 1</a></body></html>",
        CHAPTER_URL: (
            b"<html><body>"
            b"<a href='./title1sec1.html'>Section 1</a>"
            b"<a href='./title1sec2.html'>Section 2</a>"
            b"</body></html>"
        ),
    }


def _section_payload(section_number: int) -> bytes:
    return (
        "<html><body>"
        "<div class='MRSSection status_current'>"
        f"<h3 class='heading_section'>§{section_number}. Maine section {section_number}</h3>"
        "<div class='mrs-text MRSIndentedPara status_current'>"
        + (f"Official Maine section {section_number} text. " * 20)
        + "</div><div class='qhistory'>SECTION HISTORY PL 2025, c. 1, §1 (NEW).</div>"
        "</div></body></html>"
    ).encode()


def _source_bound_mrs_payload(
    *,
    title: str,
    source_section: str,
    visible_section: str | None = None,
    heading_name: str = "Former provision",
    headnotes: tuple[str, ...] = (),
    body: str = "",
    history: str = "SECTION HISTORY PL 2025, c. 1, §1 (RP).",
) -> bytes:
    visible = visible_section or source_section
    headnote_html = "".join(
        f"<div class='headnote_blip'>{text}</div>" for text in headnotes
    )
    body_html = (
        f"<div class='mrs-text MRSIndentedPara status_current'>{body}</div>"
        if body
        else ""
    )
    return (
        "<html><head>"
        f"<title>Title {title}, §{visible}: {heading_name}</title>"
        "</head><body>"
        f"<div class='MRSTitle'>Title {title}: TEST TITLE</div>"
        "<div class='col-sm-12 MRSSection status_current'>"
        f"<h3 class='heading_section'>§{visible}. {heading_name}</h3>"
        f"{headnote_html}{body_html}"
        f"<div class='qhistory'>{history}</div>"
        "</div></body></html>"
    ).encode()


def _empty_chapter_payload(heading: str) -> bytes:
    return (
        "<html><head>"
        f"<title>{heading}</title>"
        "</head><body>"
        f"<div class='ch_heading'>{heading}</div>"
        "</body></html>"
    ).encode()


def _disable_checkpoints(scraper: MaineScraper) -> None:
    scraper._load_partial_checkpoint_statutes = lambda **_kwargs: []
    scraper._load_partial_checkpoint_progress = dict
    scraper._write_partial_checkpoint = lambda *_args, **_kwargs: None


def _six_v9_terminal_pages() -> dict[str, bytes]:
    history_only = {
        ("14", "556-2", "556"): (
            "SECTION HISTORY PL 1995, c. 413, §1 (NEW). "
            "PL 2011, c. 559, Pt. A, §13 (AMD). "
            "PL 2023, c. 322, §1 (AMD). PL 2023, c. 626, §1 (RP). "
            "PL 2023, c. 626, §§3, 4, 7 (AFF)."
        ),
        ("34-A", "4102", "4102"): (
            "SECTION HISTORY PL 1991, c. 400 (NEW). "
            "PL 1997, c. 752, §41 (AMD). PL 1999, c. 401, §J6 (AMD). "
            "PL 1999, c. 583, §§39-41 (AMD). "
            "PL 1999, c. 624, §§B25,26 (AMD). "
            "PL 2001, c. 439, §G8 (AMD). PL 2003, c. 410, §18 (AMD). "
            "PL 2003, c. 545, §6 (REV). PL 2005, c. 328, §21 (RP)."
        ),
    }
    pages = {
        (
            f"https://legislature.maine.gov/statutes/{title}/"
            f"title{title}sec{section}.html"
        ): _source_bound_mrs_payload(
            title=title,
            source_section=section,
            visible_section=visible,
            history=history,
        )
        for (title, section, visible), history in history_only.items()
    }
    for title, section, visible, headnote in (
        (
            "22",
            "1553-A-2",
            "1553-A",
            "(WHOLE SECTION TEXT REPEALED 1/5/26 by PL 2025, c. 367, §§7, 20)",
        ),
        (
            "22",
            "1716-2",
            "1716",
            "(WHOLE SECTION TEXT REPEALED 7/01/26 by PL 2025, c. 488, §§2, 8)",
        ),
        (
            "36",
            "4365-F-2",
            "4365-F",
            "(WHOLE SECTION TEXT REPEALED 1/05/26)",
        ),
    ):
        url = (
            f"https://legislature.maine.gov/statutes/{title}/"
            f"title{title}sec{section}.html"
        )
        pages[url] = _source_bound_mrs_payload(
            title=title,
            source_section=section,
            visible_section=visible,
            headnotes=(headnote,),
        )

    title = "29-A"
    section = "2354-E"
    url = (
        f"https://legislature.maine.gov/statutes/{title}/"
        f"title{title}sec{section}.html"
    )
    note = (
        "Revisor's Note: Public Law 2015, chapter 119, section 6 contained a "
        "contingent effective provision. Because notification of the analysis "
        "and determination required by the contingency was not received prior "
        "to January 1, 2018, this section never took effect."
    )
    pages[url] = _source_bound_mrs_payload(
        title=title,
        source_section=section,
    ).replace(
        b"<div class='qhistory'>SECTION HISTORY PL 2025, c. 1, \xc2\xa71 (RP).</div>",
        f"<div class='note'>{note}</div>".encode(),
    )
    return pages


def test_maine_closure_source_identity_binds_parser_and_replay_closure() -> None:
    scraper = MaineScraper("ME", "Maine")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "maine_section",
        "strict_frontier_closure",
    ]
    assert "@sha256:" in scraper._state_law_frontier_source_software_version()


@pytest.mark.parametrize(
    ("source_section", "headnotes", "expected"),
    [
        ("403-A", ("(REPEALED)",), "repealed"),
        (
            "175",
            ("(REALLOCATED TO TITLE 38, SECTION 1476)",),
            "reallocated_to",
        ),
        (
            "4811-A",
            ("(REALLOCATED FROM TITLE 38, SECTION 436)",),
            "reallocated_from",
        ),
        ("1348-B", ("(PLACEHOLDER)",), "placeholder"),
        (
            "8707-2",
            (
                (
                    "(WHOLE SECTION TEXT REPEALED ON CONTINGENCY: "
                    "See PL 2013, c. 528, §12)"
                ),
                "(REPEALED)",
            ),
            "repealed_on_contingency",
        ),
        (
            "3613-2",
            (
                (
                    "(WHOLE SECTION CONFLICT: Text as repealed by "
                    "PL 2025, c. 390, Pt. A, §55)"
                ),
                "(REPEALED)",
            ),
            "repealed_conflict_variant",
        ),
        (
            "545",
            (
                (
                    "Persons required to have vision examinations "
                    "(REPEALED by PL 1977, c. 620, §1)"
                ),
                "(REPEALED)",
            ),
            "repealed",
        ),
    ],
)
def test_maine_retained_terminal_headnote_families_are_exact_and_source_bound(
    source_section: str,
    headnotes: tuple[str, ...],
    expected: str,
) -> None:
    title = "17-A" if source_section == "1348-B" else "1"
    payload = _source_bound_mrs_payload(
        title=title,
        source_section=source_section,
        headnotes=headnotes,
    )
    url = (
        f"https://legislature.maine.gov/statutes/{title}/"
        f"title{title}sec{source_section}.html"
    )

    assert source_bound_maine_section_disposition(
        payload.decode(),
        source_url=url,
    ) == expected
    assert parse_maine_section_html(payload.decode(), source_url=url) is None


@pytest.mark.parametrize(
    ("title", "section", "headnotes"),
    [
        (
            "12",
            "6728-A",
            (
                "(REALLOCATED FROM TITLE 12, SECTION 6729)",
                "(REALLOCATED TO TITLE 12, SECTION 6721-A)",
            ),
        ),
        (
            "38",
            "1310-A",
            (
                "(REALLOCATED FROM TITLE 38, SECTION 1311)",
                "(REALLOCATED TO TITLE 38, SECTION 1319-P)",
            ),
        ),
    ],
)
def test_maine_observed_mixed_reallocation_terminals_are_typed(
    title: str,
    section: str,
    headnotes: tuple[str, ...],
) -> None:
    payload = _source_bound_mrs_payload(
        title=title,
        source_section=section,
        headnotes=headnotes,
    ).decode()
    url = (
        f"https://legislature.maine.gov/statutes/{title}/"
        f"title{title}sec{section}.html"
    )

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) == "reallocated"
    assert parse_maine_section_html(payload, source_url=url) is None


def test_maine_terminal_classifier_accepts_only_complete_heading_or_body_marker() -> None:
    url = "https://legislature.maine.gov/statutes/1/title1sec99.html"
    heading_marker = _source_bound_mrs_payload(
        title="1",
        source_section="99",
        heading_name="(REPEALED)",
    ).decode()
    body_marker = _source_bound_mrs_payload(
        title="1",
        source_section="99",
        body="(REPEALED)",
    ).decode()

    assert source_bound_maine_section_disposition(
        heading_marker,
        source_url=url,
    ) == "repealed"
    assert source_bound_maine_section_disposition(
        body_marker,
        source_url=url,
    ) == "repealed"
    assert source_bound_maine_section_disposition(
        body_marker.replace("(REPEALED)", "This cites a (REPEALED) prior law."),
        source_url=url,
    ) is None


def test_maine_terminal_classifier_accepts_blank_caption_repealed_page() -> None:
    url = "https://legislature.maine.gov/statutes/20/title20sec3211.html"
    payload = _source_bound_mrs_payload(
        title="20",
        source_section="3211",
        heading_name="",
        headnotes=("(REPEALED)",),
    ).decode()

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) == "repealed"


def test_maine_terminal_marker_normalizes_only_closing_punctuation_whitespace() -> None:
    url = (
        "https://legislature.maine.gov/statutes/20-A/"
        "title20-Asec1481-B.html"
    )
    payload = _source_bound_mrs_payload(
        title="20-A",
        source_section="1481-B",
        headnotes=("(REPEALED )",),
        history=(
            "SECTION HISTORY PL 2007, c. 668, §16 (NEW). "
            "MRSA T. 20-A §1481-B (RP)."
        ),
    ).decode()

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) == "repealed"
    assert parse_maine_section_html(payload, source_url=url) is None
    assert source_bound_maine_section_disposition(
        payload.replace("(REPEALED )", "(REPEALED BY UNKNOWN AUTHORITY )"),
        source_url=url,
    ) is None
    assert source_bound_maine_section_disposition(
        payload.replace("(REPEALED )", "This cites a (REPEALED ) prior law."),
        source_url=url,
    ) is None


@pytest.mark.parametrize(
    ("title", "section", "headnote"),
    [
        (
            "22",
            "1553-A-2",
            (
                "(WHOLE SECTION TEXT REPEALED 1/5/26 by "
                "PL 2025, c. 367, §§7, 20)"
            ),
        ),
        (
            "22",
            "1716-2",
            (
                "(WHOLE SECTION TEXT REPEALED 7/01/26 by "
                "PL 2025, c. 488, §§2, 8)"
            ),
        ),
        ("36", "4365-F-2", "(WHOLE SECTION TEXT REPEALED 1/05/26)"),
    ],
)
def test_maine_dated_repeal_terminals_are_exact_locator_bound(
    title: str,
    section: str,
    headnote: str,
) -> None:
    url = (
        f"https://legislature.maine.gov/statutes/{title}/"
        f"title{title}sec{section}.html"
    )
    visible_section = section.rsplit("-", 1)[0] if section.endswith("-2") else section
    payload = _source_bound_mrs_payload(
        title=title,
        source_section=section,
        visible_section=visible_section,
        headnotes=(headnote,),
    ).decode()

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) == "repealed_effective_dated"
    assert source_bound_maine_section_disposition(
        payload.replace("1/5/26", "1/6/26")
        .replace("7/01/26", "7/02/26")
        .replace("1/05/26", "1/06/26"),
        source_url=url,
    ) is None


def test_maine_never_effective_note_only_terminal_is_exact_body_bound() -> None:
    url = "https://legislature.maine.gov/statutes/29-A/title29-Asec2354-E.html"
    note = (
        "Revisor's Note: Public Law 2015, chapter 119, section 6 contained a "
        "contingent effective provision. Because notification of the analysis "
        "and determination required by the contingency was not received prior "
        "to January 1, 2018, this section never took effect."
    )
    payload = _source_bound_mrs_payload(
        title="29-A",
        source_section="2354-E",
    ).decode().replace(
        "<div class='qhistory'>SECTION HISTORY PL 2025, c. 1, §1 (RP).</div>",
        f"<div class='note'>{note}</div>",
    )

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) == "never_effective"
    assert source_bound_maine_section_disposition(
        payload.replace("never took effect", "might take effect"),
        source_url=url,
    ) is None


def test_maine_terminal_classifier_rejects_source_identity_and_dom_drift() -> None:
    url = "https://legislature.maine.gov/statutes/1/title1sec403-A.html"
    payload = _source_bound_mrs_payload(
        title="1",
        source_section="403-A",
        headnotes=("(REPEALED)",),
    ).decode()

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url.replace("403-A", "403-B"),
    ) is None
    assert source_bound_maine_section_disposition(
        payload.replace("Title 1,", "Title 2,"),
        source_url=url,
    ) is None
    assert source_bound_maine_section_disposition(
        payload.replace("(REPEALED)", "(REPEALED BY UNKNOWN AUTHORITY)"),
        source_url=url,
    ) is None
    assert source_bound_maine_section_disposition(
        payload.replace(
            "<div class='qhistory'>",
            "<div class='mrs-text'>Substantive text remains.</div>"
            "<div class='qhistory'>",
        ),
        source_url=url,
    ) is None


@pytest.mark.parametrize(
    ("title", "source_section", "visible_section", "history"),
    [
        (
            "14",
            "556-2",
            "556",
            (
                "SECTION HISTORY PL 1995, c. 413, §1 (NEW). "
                "PL 2011, c. 559, Pt. A, §13 (AMD). "
                "PL 2023, c. 322, §1 (AMD). PL 2023, c. 626, §1 (RP). "
                "PL 2023, c. 626, §§3, 4, 7 (AFF)."
            ),
        ),
        (
            "34-A",
            "4102",
            "4102",
            (
                "SECTION HISTORY PL 1991, c. 400 (NEW). "
                "PL 1997, c. 752, §41 (AMD). PL 1999, c. 401, §J6 (AMD). "
                "PL 1999, c. 583, §§39-41 (AMD). "
                "PL 1999, c. 624, §§B25,26 (AMD). "
                "PL 2001, c. 439, §G8 (AMD). PL 2003, c. 410, §18 (AMD). "
                "PL 2003, c. 545, §6 (REV). PL 2005, c. 328, §21 (RP)."
            ),
        ),
        (
            "34-A",
            "5403",
            "5403",
            (
                "SECTION HISTORY PL 1983, c. 459, §6 (NEW). "
                "PL 1995, c. 502, §F35 (RP)."
            ),
        ),
        (
            "17",
            "3241",
            "3241",
            "SECTION HISTORY PL 2025, c. 43, §4 (RP).",
        ),
    ],
)
def test_maine_history_only_terminals_are_exact_locator_and_history_bound(
    title: str,
    source_section: str,
    visible_section: str,
    history: str,
) -> None:
    payload = _source_bound_mrs_payload(
        title=title,
        source_section=source_section,
        visible_section=visible_section,
        history=history,
    ).decode()
    url = (
        f"https://legislature.maine.gov/statutes/{title}/"
        f"title{title}sec{source_section}.html"
    )

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) == "repealed"
    assert source_bound_maine_section_disposition(
        payload.replace("(RP)", "(AMD)"),
        source_url=url,
    ) is None


def test_maine_parser_preserves_source_bound_short_operative_text() -> None:
    url = "https://legislature.maine.gov/statutes/1/title1sec99.html"
    payload = _source_bound_mrs_payload(
        title="1",
        source_section="99",
        body="It applies.",
        history="SECTION HISTORY PL 2025, c. 1, §1 (NEW).",
    ).decode()

    row = parse_maine_section_html(payload, source_url=url)

    assert row is not None
    assert row.section_number == "99"
    assert row.full_text == "It applies."


def test_maine_parser_keeps_operative_reference_to_repealed_law() -> None:
    url = "https://legislature.maine.gov/statutes/1/title1sec100.html"
    text = (
        "This current section preserves claims arising under a prior "
        "(REPEALED) provision and remains operative."
    )
    payload = _source_bound_mrs_payload(
        title="1",
        source_section="100",
        body=text,
        history="SECTION HISTORY PL 2025, c. 1, §1 (NEW).",
    ).decode()

    row = parse_maine_section_html(payload, source_url=url)

    assert row is not None
    assert row.full_text == text


def test_maine_parser_preserves_operative_reallocated_from_section() -> None:
    url = "https://legislature.maine.gov/statutes/1/title1sec141.html"
    text = (
        "The first Saturday of September is designated as Colonel Freeman "
        "McGilvery Day, and the Governor shall issue a proclamation."
    )
    payload = _source_bound_mrs_payload(
        title="1",
        source_section="141",
        headnotes=("(REALLOCATED FROM TITLE 1, SECTION 139)",),
        body=text,
        history="SECTION HISTORY RR 2001, c. 1, §1 (RAL).",
    ).decode()

    row = parse_maine_section_html(payload, source_url=url)

    assert row is not None
    assert row.full_text == "(REALLOCATED FROM TITLE 1, SECTION 139) " + text


def test_maine_parser_fails_closed_on_reallocated_to_marker_with_body() -> None:
    url = "https://legislature.maine.gov/statutes/1/title1sec139.html"
    payload = _source_bound_mrs_payload(
        title="1",
        source_section="139",
        headnotes=("(REALLOCATED TO TITLE 1, SECTION 141)",),
        body="Ambiguous text remains at the old official locator.",
    ).decode()

    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) is None
    assert parse_maine_section_html(payload, source_url=url) is None


def test_maine_parser_preserves_exact_incorporation_by_reference_note() -> None:
    url = "https://legislature.maine.gov/statutes/10/title10sec1351.html"
    note = (
        "Revisor's Note: In accordance with the provisions of chapter 181 of "
        "the resolves of 1953 for the revision of statutes, chapter 162 of the "
        "Revised Statutes of 1954, entitled \"The Insolvent Law\", was "
        "incorporated and printed by title only. It is similarly incorporated "
        "herein and may be cited as 10 MRSA 1351. The laws relating to "
        "insolvency may be found in chapter 72 of the Revised Statutes of 1903, "
        "as amended by chapter 90 of the Public Laws of 1923, chapter 76 of the "
        "Public Laws of 1927 and chapter 149 of the Revised Statutes of 1944."
    )
    payload = _source_bound_mrs_payload(
        title="10",
        source_section="1351",
        heading_name="Insolvent law",
    ).decode().replace(
        "<div class='qhistory'>SECTION HISTORY PL 2025, c. 1, §1 (RP).</div>",
        "<div class='mrs-text MRSIndentedPara status_current'></div>"
        f"<div class='note'>{note}</div>",
    )

    row = parse_maine_section_html(payload, source_url=url)

    assert row is not None
    assert row.full_text == note
    assert source_bound_maine_section_disposition(
        payload,
        source_url=url,
    ) is None
    assert parse_maine_section_html(
        payload.replace("similarly incorporated", "possibly incorporated"),
        source_url=url,
    ) is None


@pytest.mark.parametrize(
    ("source_url", "catalog_label", "heading", "expected_disposition"),
    TERMINAL_CHAPTER_CASES,
)
def test_maine_empty_chapter_terminal_is_bound_to_exact_official_contract(
    source_url: str,
    catalog_label: str,
    heading: str,
    expected_disposition: str,
) -> None:
    payload = _empty_chapter_payload(heading).decode()

    assert source_bound_maine_chapter_disposition(
        payload,
        source_url=source_url,
        title_catalog_label=catalog_label,
    ) == expected_disposition


@pytest.mark.parametrize(
    ("source_url", "catalog_label", "heading", "_expected_disposition"),
    TERMINAL_CHAPTER_CASES,
)
def test_maine_empty_chapter_terminal_rejects_source_contract_drift(
    source_url: str,
    catalog_label: str,
    heading: str,
    _expected_disposition: str,
) -> None:
    payload = _empty_chapter_payload(heading).decode()
    operative_link = payload.replace(
        "</body>",
        "<a href='./title22sec9999.html'>§9999</a></body>",
    )

    assert source_bound_maine_chapter_disposition(
        payload,
        source_url=source_url.replace("https://", "http://"),
        title_catalog_label=catalog_label,
    ) is None
    assert source_bound_maine_chapter_disposition(
        payload,
        source_url=source_url,
        title_catalog_label=f"{catalog_label} changed",
    ) is None
    assert source_bound_maine_chapter_disposition(
        payload.replace(heading, f"{heading} changed", 1),
        source_url=source_url,
        title_catalog_label=catalog_label,
    ) is None
    assert source_bound_maine_chapter_disposition(
        operative_link,
        source_url=source_url,
        title_catalog_label=catalog_label,
    ) is None


def test_maine_exact_frontier_rejects_terminal_canonical_overlap() -> None:
    scraper = MaineScraper("ME", "Maine")
    shared_key = "urn:state:me:statute:Maine Revised Statutes shared"

    with pytest.raises(RuntimeError, match="not disjoint and exact"):
        scraper._maine_exact_frontier(
            root_content_sha256="a" * 64,
            expected_title_count=1,
            title_reports=[
                {
                    "chapter_count": 1,
                    "content_sha256": "b" * 64,
                    "source_url": TITLE_URL,
                }
            ],
            chapter_reports=[
                {
                    "content_sha256": "c" * 64,
                    "disposition": "section_frontier",
                    "section_count": 2,
                    "source_url": CHAPTER_URL,
                    "title_source_url": TITLE_URL,
                }
            ],
            section_reports=[
                {
                    "canonical_identity": shared_key,
                    "content_sha256": "d" * 64,
                    "disposition": "operative",
                    "section_number": "1",
                    "source_url": SECTION_URLS[0],
                    "title_number": "1",
                },
                {
                    "canonical_identity": shared_key,
                    "content_sha256": "e" * 64,
                    "disposition": "repealed",
                    "section_number": "2",
                    "source_url": SECTION_URLS[1],
                    "title_number": "1",
                },
            ],
        )


@pytest.mark.anyio
async def test_maine_chapter_submits_exact_section_frontier_direct_first(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    discovery_pages = _discovery_pages()
    single_calls: list[str] = []
    frontier_calls: list[tuple[list[str], dict[str, object]]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        single_calls.append(url)
        assert url not in SECTION_URLS
        return discovery_pages.get(url, b"")

    async def _frontier(self, urls, **kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        frontier_calls.append((requested, dict(kwargs)))
        payloads = [_section_payload(SECTION_URLS.index(url) + 1) for url in requested]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"requested_pages": len(requested)},
        )

    monkeypatch.setenv("STATE_SCRAPER_ME_SECTION_CONCURRENCY", "3")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setattr(MaineScraper, "_fetch_page_content_with_archival_fallback", _single)
    monkeypatch.setattr(MaineScraper, "_fetch_page_contents_with_archival_fallback", _frontier)

    scraper = MaineScraper("ME", "Maine")
    _disable_checkpoints(scraper)
    statutes = await scraper._scrape_official_title_chapter_section_tree(
        "Maine Revised Statutes",
        max_statutes=2,
    )

    assert single_calls == [ROOT_URL, TITLE_URL, CHAPTER_URL]
    assert [requested for requested, _kwargs in frontier_calls] == [SECTION_URLS]
    assert frontier_calls[0][1] == {
        "timeout_seconds": 25,
        "max_concurrency": 3,
        "prefer_direct": True,
    }
    assert [statute.source_url for statute in statutes] == SECTION_URLS
    assert [statute.section_number for statute in statutes] == ["1", "2"]


@pytest.mark.anyio
async def test_maine_chapter_rejects_reordered_section_frontier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    discovery_pages = _discovery_pages()

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        return discovery_pages.get(url, b"")

    async def _reordered_frontier(self, urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return StateLawPageMultiFetchResult(
            urls=list(reversed(requested)),
            payloads=[_section_payload(1), _section_payload(2)],
            errors=[None, None],
            transport_receipts=[None, None],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setattr(MaineScraper, "_fetch_page_content_with_archival_fallback", _single)
    monkeypatch.setattr(
        MaineScraper,
        "_fetch_page_contents_with_archival_fallback",
        _reordered_frontier,
    )

    scraper = MaineScraper("ME", "Maine")
    _disable_checkpoints(scraper)
    with pytest.raises(RuntimeError, match="changed URL order or identity"):
        await scraper._scrape_official_title_chapter_section_tree(
            "Maine Revised Statutes",
            max_statutes=2,
        )


@pytest.mark.anyio
async def test_maine_unbounded_crawl_batches_known_title_index_frontier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    pages = {
        ROOT_URL: (
            b"<html><body>"
            b"<a href='1/title1ch0sec0.html'>TITLE 1</a>"
            b"<a href='2/title2ch0sec0.html'>TITLE 2</a>"
            b"</body></html>"
        ),
        TITLE_URL: b"<html><body><a href='./title1ch1sec0.html'>Chapter 1</a></body></html>",
        TITLE_2_URL: b"<html><body><a href='./title2ch1sec0.html'>Chapter 1</a></body></html>",
        CHAPTER_URL: b"<html><body><a href='./title1sec1.html'>Section 1</a></body></html>",
        CHAPTER_2_URL: b"<html><body><a href='./title2sec1.html'>Section 1</a></body></html>",
        SECTION_URLS[0]: _section_payload(1),
        SECTION_2_URL: _section_payload(1),
    }
    single_calls: list[str] = []
    frontier_calls: list[tuple[list[str], dict[str, object]]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        single_calls.append(url)
        return pages.get(url, b"")

    async def _frontier(self, urls, **kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        frontier_calls.append((requested, dict(kwargs)))
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[pages[url] for url in requested],
            errors=[None] * len(requested),
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"requested_pages": len(requested)},
        )

    monkeypatch.setenv("STATE_SCRAPER_ME_SECTION_CONCURRENCY", "3")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setattr(MaineScraper, "_fetch_page_content_with_archival_fallback", _single)
    monkeypatch.setattr(MaineScraper, "_fetch_page_contents_with_archival_fallback", _frontier)

    scraper = MaineScraper("ME", "Maine")
    _disable_checkpoints(scraper)
    statutes = await scraper._scrape_official_title_chapter_section_tree(
        "Maine Revised Statutes"
    )

    assert single_calls == [ROOT_URL]
    assert [requested for requested, _kwargs in frontier_calls] == [
        [TITLE_URL, TITLE_2_URL],
        [CHAPTER_URL],
        [SECTION_URLS[0]],
        [CHAPTER_2_URL],
        [SECTION_2_URL],
    ]
    assert all(
        kwargs
        == {
            "timeout_seconds": 25,
            "max_concurrency": 3,
            "prefer_direct": True,
        }
        for _requested, kwargs in frontier_calls
    )
    assert [statute.source_url for statute in statutes] == [
        SECTION_URLS[0],
        SECTION_2_URL,
    ]
    assert [statute.title_number for statute in statutes] == ["1", "2"]
    assert len({statute.statute_id for statute in statutes}) == 2
    assert statutes[0].statute_id.endswith("tit. 1, § 1")
    assert statutes[1].statute_id.endswith("tit. 2, § 1")


@pytest.mark.anyio
async def test_maine_unbounded_crawl_rejects_reordered_title_frontier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    root = (
        b"<html><body>"
        b"<a href='1/title1ch0sec0.html'>TITLE 1</a>"
        b"<a href='2/title2ch0sec0.html'>TITLE 2</a>"
        b"</body></html>"
    )

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == ROOT_URL
        return root

    async def _reordered_frontier(self, urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return StateLawPageMultiFetchResult(
            urls=list(reversed(requested)),
            payloads=[b"title two", b"title one"],
            errors=[None, None],
            transport_receipts=[None, None],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setattr(MaineScraper, "_fetch_page_content_with_archival_fallback", _single)
    monkeypatch.setattr(
        MaineScraper,
        "_fetch_page_contents_with_archival_fallback",
        _reordered_frontier,
    )

    scraper = MaineScraper("ME", "Maine")
    _disable_checkpoints(scraper)
    with pytest.raises(RuntimeError, match="title-index frontier changed URL order"):
        await scraper._scrape_official_title_chapter_section_tree(
            "Maine Revised Statutes"
        )


@pytest.mark.anyio
async def test_maine_unbounded_crawl_records_typed_terminal_and_excludes_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    terminal_payload = _source_bound_mrs_payload(
        title="1",
        source_section="2",
        headnotes=("(REPEALED)",),
    )
    pages = {
        ROOT_URL: b"<html><body><a href='1/title1ch0sec0.html'>TITLE 1</a></body></html>",
        TITLE_URL: b"<html><body><a href='./title1ch1sec0.html'>Chapter 1</a></body></html>",
        CHAPTER_URL: (
            b"<html><body>"
            b"<a href='./title1sec1.html'>Section 1</a>"
            b"<a href='./title1sec2.html'>Section 2</a>"
            b"</body></html>"
        ),
        SECTION_URLS[0]: _section_payload(1),
        SECTION_URLS[1]: terminal_payload,
    }
    checkpoints: list[dict[str, object]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        return pages.get(url, b"")

    async def _frontier(self, urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        payloads = [pages.get(url, b"") for url in requested]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None if payload else "test miss" for payload in payloads],
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"requested_pages": len(requested)},
        )

    def _checkpoint(_self, _statutes, **kwargs) -> None:
        checkpoints.append(dict(kwargs))

    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setattr(MaineScraper, "_fetch_page_content_with_archival_fallback", _single)
    monkeypatch.setattr(MaineScraper, "_fetch_page_contents_with_archival_fallback", _frontier)
    monkeypatch.setattr(MaineScraper, "_write_partial_checkpoint", _checkpoint)
    scraper = MaineScraper("ME", "Maine")

    rows = await scraper._scrape_official_title_chapter_section_tree(
        "Maine Revised Statutes"
    )

    assert [row.source_url for row in rows] == [SECTION_URLS[0]]
    assert checkpoints
    assert all(checkpoint["replace_existing_rows"] is True for checkpoint in checkpoints)
    complete = checkpoints[-1]
    assert complete["stage_label"] == "maine:complete"
    extra = complete["extra"]
    assert extra["terminal_sections_classified"] == 1
    assert extra["terminal_disposition_counts"] == {"repealed": 1}
    assert extra["terminal_section_dispositions"] == [
        {
            "content_sha256": hashlib.sha256(terminal_payload).hexdigest(),
            "disposition": "repealed",
            "section_number": "2",
            "source_url": SECTION_URLS[1],
        }
    ]


@pytest.mark.anyio
async def test_maine_unbounded_crawl_fails_closed_on_unknown_mrs_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    unknown_payload = _source_bound_mrs_payload(
        title="1",
        source_section="1",
        body=".",
    )
    pages = {
        ROOT_URL: b"<html><body><a href='1/title1ch0sec0.html'>TITLE 1</a></body></html>",
        TITLE_URL: b"<html><body><a href='./title1ch1sec0.html'>Chapter 1</a></body></html>",
        CHAPTER_URL: b"<html><body><a href='./title1sec1.html'>Section 1</a></body></html>",
        SECTION_URLS[0]: unknown_payload,
    }

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        return pages.get(url, b"")

    async def _frontier(self, urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        payloads = [pages.get(url, b"") for url in requested]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={},
        )

    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setattr(MaineScraper, "_fetch_page_content_with_archival_fallback", _single)
    monkeypatch.setattr(MaineScraper, "_fetch_page_contents_with_archival_fallback", _frontier)
    scraper = MaineScraper("ME", "Maine")
    _disable_checkpoints(scraper)

    with pytest.raises(RuntimeError, match="no source-bound terminal disposition"):
        await scraper._scrape_official_title_chapter_section_tree(
            "Maine Revised Statutes"
        )


@pytest.mark.anyio
async def test_maine_retained_frontier_types_exact_empty_chapters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    active_section_url = (
        "https://legislature.maine.gov/statutes/22/title22sec2541.html"
    )
    terminal_pages = {
        source_url: _empty_chapter_payload(heading)
        for source_url, _label, heading, _disposition in TERMINAL_CHAPTER_CASES
    }
    title_links = [
        (
            ACTIVE_CHAPTER_22_URL,
            "Chapter 564: MAINE MEAT INSPECTION ACT",
        ),
        *[
            (source_url, label)
            for source_url, label, _heading, _disposition in TERMINAL_CHAPTER_CASES
        ],
    ]
    pages: dict[str, bytes] = {
        ROOT_URL: (
            "<html><body><a href='22/title22ch0sec0.html'>TITLE 22</a>"
            "</body></html>"
        ).encode(),
        TITLE_22_URL: (
            "<html><body>"
            + "".join(
                "<div class='MRSChapter_toclist'>"
                f"<a href='./{url.rsplit('/', 1)[-1]}'>{label}</a></div>"
                for url, label in title_links
            )
            + "</body></html>"
        ).encode(),
        ACTIVE_CHAPTER_22_URL: (
            "<html><body><a href='./title22sec2541.html'>§2541</a>"
            "</body></html>"
        ).encode(),
        active_section_url: _source_bound_mrs_payload(
            title="22",
            source_section="2541",
            heading_name="Current provision",
            body=("This exact Maine statutory provision remains operative. " * 5),
            history="SECTION HISTORY PL 2025, c. 1, §1 (NEW).",
        ),
        **terminal_pages,
    }

    scraper = MaineScraper("ME", "Maine")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "me-empty-chapter-evidence",
        jurisdiction="ME",
        parser_name=type(scraper).__name__,
    )
    for url, body in pages.items():
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at="2026-08-25T21:00:00Z",
            sanitized_request={"method": "GET", "url": url},
        )
    scraper.attach_state_law_acquisition_ledger(ledger)
    _disable_checkpoints(scraper)
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", 1)
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    async def _forbid_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Maine retained exact inputs must perform zero network")

    monkeypatch.setattr(
        ArchivalFetchClient,
        "fetch_many_with_fallback",
        _forbid_network,
    )
    rows = await scraper._scrape_official_title_chapter_section_tree(
        "Maine Revised Statutes"
    )

    assert [row.source_url for row in rows] == [active_section_url]
    frontier = scraper._last_maine_full_frontier["frontier"]
    assert frontier["chapter_document_count"] == 3
    assert frontier["active_chapter_document_count"] == 1
    assert frontier["terminal_chapter_document_count"] == 2
    assert frontier["terminal_chapter_dispositions"] == {
        "never_effective_chapter": 1,
        "repealed_chapter": 1,
    }
    terminal_chapters = scraper._last_maine_full_frontier[
        "terminal_chapter_dispositions"
    ]
    assert [row["source_url"] for row in terminal_chapters] == [
        case[0] for case in TERMINAL_CHAPTER_CASES
    ]
    assert all(re.fullmatch(r"[0-9a-f]{64}", row["content_sha256"])
               for row in terminal_chapters)

    replay_rows = await scraper._scrape_official_title_chapter_section_tree(
        "Maine Revised Statutes",
        record_primary=False,
        write_checkpoints=False,
        retained_only=True,
    )
    assert [row.source_url for row in replay_rows] == [active_section_url]
    assert (
        scraper._last_maine_replayed_frontier["frontier"]
        == scraper._last_maine_full_frontier["frontier"]
    )
    assert all(
        int(batch.get("network_requested_pages") or 0) == 0
        for batch in scraper._last_maine_replayed_frontier["transport_batch_stats"]
    )


@pytest.mark.anyio
async def test_maine_retained_strict_replay_reclassifies_all_six_v9_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    terminal_pages = _six_v9_terminal_pages()
    sections_by_title: dict[str, list[str]] = {
        "14": ["1", "556-2"],
        "22": ["1553-A-2", "1716-2"],
        "29-A": ["2354-E"],
        "34-A": ["4102"],
        "36": ["4365-F-2"],
    }
    title_urls = {
        title: (
            f"https://legislature.maine.gov/statutes/{title}/"
            f"title{title}ch0sec0.html"
        )
        for title in sections_by_title
    }
    chapter_urls = {
        title: (
            f"https://legislature.maine.gov/statutes/{title}/"
            f"title{title}ch1sec0.html"
        )
        for title in sections_by_title
    }
    pages: dict[str, bytes] = {
        ROOT_URL: (
            "<html><body>"
            + "".join(
                f"<a href='{title}/title{title}ch0sec0.html'>TITLE {title}</a>"
                for title in sections_by_title
            )
            + "</body></html>"
        ).encode()
    }
    for title, sections in sections_by_title.items():
        pages[title_urls[title]] = (
            f"<html><body><a href='./title{title}ch1sec0.html'>"
            "Chapter 1</a></body></html>"
        ).encode()
        pages[chapter_urls[title]] = (
            "<html><body>"
            + "".join(
                f"<a href='./title{title}sec{section}.html'>Section {section}</a>"
                for section in sections
            )
            + "</body></html>"
        ).encode()
    pages.update(terminal_pages)
    operative_url = "https://legislature.maine.gov/statutes/14/title14sec1.html"
    pages[operative_url] = _source_bound_mrs_payload(
        title="14",
        source_section="1",
        heading_name="Current provision",
        body=("This exact Maine statutory provision remains operative. " * 5),
        history="SECTION HISTORY PL 2025, c. 1, §1 (NEW).",
    )

    scraper = MaineScraper("ME", "Maine")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "me-retained-evidence",
        jurisdiction="ME",
        parser_name=type(scraper).__name__,
    )
    for url, body in pages.items():
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at="2026-08-25T21:00:00Z",
            sanitized_request={"method": "GET", "url": url},
        )
    scraper.attach_state_law_acquisition_ledger(ledger)
    _disable_checkpoints(scraper)
    monkeypatch.setattr(scraper, "OFFICIAL_TITLE_COUNT", len(title_urls))
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )

    async def _forbid_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Maine retained strict replay must perform zero network")

    monkeypatch.setattr(
        ArchivalFetchClient,
        "fetch_many_with_fallback",
        _forbid_network,
    )
    rows = await scraper._scrape_official_title_chapter_section_tree(
        "Maine Revised Statutes"
    )

    assert [row.source_url for row in rows] == [operative_url]
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        rows[0].structured_data["parser_input_receipt_sha256"],
    )
    assert rows[0].structured_data["content_sha256"] == hashlib.sha256(
        pages[operative_url]
    ).hexdigest()
    frontier = scraper._last_maine_full_frontier["frontier"]
    assert frontier["catalog_observed_units"] == 5
    assert frontier["chapter_document_count"] == 5
    assert frontier["disposition"] == {
        "discovered": 7,
        "fetched": 1,
        "excluded": 6,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert frontier["terminal_dispositions"] == {
        "never_effective": 1,
        "repealed": 2,
        "repealed_effective_dated": 3,
    }

    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="ME",
    )
    retained: dict[str, object] = {}

    def _retain(completion: dict[str, object], **kwargs: object) -> Path:
        retained["completion"] = completion
        retained["kwargs"] = kwargs
        return tmp_path / "STATE-ME.frontier-closure.json"

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["me-legislature"],
    )
    closure_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert closure_path == tmp_path / "STATE-ME.frontier-closure.json"
    completion = retained["completion"]
    assert completion["disposition"] == frontier["disposition"]
    assert completion["edition"] == "2026"
    assert completion["legal_as_of"] == "2026-07-01T00:00:00Z"
    assert completion["observed_at"] == "2026-08-25T21:00:00Z"
    assert completion["replay"] == {
        "closed": True,
        "first_frontier_digest": frontier["frontier_digest_sha256"],
        "network_requests": 0,
        "second_frontier_digest": frontier["frontier_digest_sha256"],
        "source": "retained_parser_inputs",
    }
    assert completion["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["transport"]["retained_source_observation"] == {
        "first_retrieved_at": "2026-08-25T21:00:00Z",
        "last_retrieved_at": "2026-08-25T21:00:00Z",
        "unique_parser_input_count": len(pages),
    }
    assert not set(projection["canonical_keys"]) & set(
        scraper._last_maine_full_frontier["terminal_canonical_keys"]
    )
    assert retained["kwargs"]["replayed_frontier"] == frontier
