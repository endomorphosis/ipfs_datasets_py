"""Municipal collector gate, locators, and citation form."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
    format_bluebook,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.municipal_corpus import (
    admit_municipal_row,
    collect_municipal_row,
    municipal_place_status,
)

_ORDINANCE = (
    "Title 1 Administration\n"
    "Chapter 1 General\n"
    "Section 1.01 The city shall keep the peace.\n"
    "(a) This duty is continuous.\n"
    "Section 1.02 The council shall meet monthly.\n"
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "authority": "Hamilton",
        "jurisdiction": "US-OH",
        "doc_type": "ordinance",
        "language": "en",
        "source_official": True,
        "source_url": "https://www.cityofhamilton.us/code",
        "text": _ORDINANCE,
        "citation_year": "2020",
        "entry_cid": "hamilton-code",
    }
    row.update(overrides)
    return row


def test_chrome_blog_and_title_shell_produce_no_atom_text() -> None:
    breadcrumb = _row(
        doc_type="ordinance",
        text="Home\nSearch\nContact us\nThis website uses cookies\n",
        title="Search",
    )
    website = _row(
        doc_type="website",
        text="Home\nSearch\nContact us\nThis website uses cookies\n",
        title="Search",
    )
    blog = _row(
        doc_type="blog",
        text="The mayor shall post a weekend blog about the festival.",
        source_url="https://www.cityofhamilton.us/blog",
    )
    newsletter = _row(
        doc_type="newsletter",
        text="Subscribe to the city newsletter for event announcements.",
    )
    shell = _row(
        title="Hamilton municipal organization chart",
        text="Hamilton municipal organization chart",
    )
    directory = _row(
        authority="Ventura",
        source_url="https://www.citydirectory.us/ventura",
        text=_ORDINANCE,
    )
    for row, reason in (
        (breadcrumb, "site_chrome"),
        (website, "site_type"),
        (blog, "site_type"),
        (newsletter, "site_type"),
        (shell, "title_shell"),
        (directory, "unrelated_host"),
    ):
        decision = collect_municipal_row(row)
        assert decision.accept is False
        assert decision.reason == reason
        admission = admit_municipal_row(row)
        assert admission.atoms == ()
        assert admission.reason == reason


def test_two_sections_keep_the_parenthetical_on_the_first() -> None:
    admission = admit_municipal_row(_row())
    assert admission.reason == "law"
    assert len(admission.atoms) == 2
    first, second = admission.atoms
    assert first["provenance"]["section"] == "1.01"
    assert first["provenance"]["subsection"] == "a"
    assert "continuous" in str(first["text"])
    assert second["text"].startswith("Section 1.02")
    assert "(a)" not in str(second["text"])
    assert first["provenance"]["document_role"] == "law"
    assert second["provenance"]["document_role"] == "law"


def test_us_year_is_bluebook_and_a_missing_year_is_an_analog() -> None:
    dated = admit_municipal_row(_row())
    expected = format_bluebook("Hamilton", "Ohio", "1.01", "2020", "Municipal Code")
    assert dated.atoms[0]["citation"] == expected
    assert dated.atoms[0]["bluebook_citation"] == expected
    assert dated.atoms[0]["provenance"]["citation_form"] == "bluebook"
    second = format_bluebook("Hamilton", "Ohio", "1.02", "2020", "Municipal Code")
    assert dated.atoms[1]["citation"] == second
    assert dated.atoms[1]["bluebook_citation"] == second
    assert dated.atoms[1]["provenance"]["section"] == "1.02"
    assert dated.atoms[1]["provenance"]["citation_form"] == "bluebook"
    undated = admit_municipal_row(_row(citation_year=""))
    bare = format_bluebook("Hamilton", "Ohio", "1.01", "", "Municipal Code")
    assert undated.atoms[0]["citation"] == bare
    assert "(" not in str(undated.atoms[0]["citation"])
    assert undated.atoms[0]["bluebook_citation"] is None
    assert undated.atoms[0]["provenance"]["citation_form"] == "analog"
    county = admit_municipal_row(
        _row(
            authority="Ventura County",
            source_url="https://www.venturacounty.us/code",
            jurisdiction="US-CA",
        )
    )
    assert county.atoms[0]["citation"] == format_bluebook(
        "Ventura County", "Cal.", "1.01", "2020", "County Code"
    )
    assert county.atoms[0]["provenance"]["citation_form"] == "bluebook"


def test_a_foreign_ordinance_is_an_analog_and_not_a_us_code() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Lyon",
            jurisdiction="FR",
            source_url="https://www.ville-lyon.fr/code",
            citation_year="2020",
        )
    )
    cite = str(admission.atoms[0]["citation"])
    assert admission.atoms[0]["bluebook_citation"] is None
    assert admission.atoms[0]["provenance"]["citation_form"] == "analog"
    assert cite == "Lyon, France, ordinance 1.01"
    assert admission.atoms[0]["provenance"]["section"] == "1.01"
    assert admission.atoms[0]["provenance"]["subsection"] == "a"
    assert "Ohio" not in cite
    assert "U.S.C." not in cite


def test_a_place_with_no_atoms_is_a_coverage_gap() -> None:
    assert municipal_place_status(resolved=True, admitted=0, refused=0) == "coverage_gap"
    assert municipal_place_status(resolved=True, admitted=0, refused=2) == "not_a_law"
    assert municipal_place_status(resolved=True, admitted=1, refused=0) == "law"
    assert municipal_place_status(resolved=False, admitted=0, refused=0) == "unknown_place"


def test_municipal_codes_is_not_a_collector_host() -> None:
    decision = collect_municipal_row(
        _row(source_url="https://bakersfield.municipal.codes/")
    )
    assert decision.accept is False
    assert decision.reason == "no_collector"
