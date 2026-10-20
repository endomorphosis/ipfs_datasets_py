"""Citation parsing for American municipal chunk titles and history notes."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
    adoption_line_dates,
    extract_history_notes,
    extract_title_num,
    html_rows_to_citation_rows,
    parse_history_fields,
    parse_year,
    passage_dates,
    source_url_from_html,
)


def test_section_number_does_not_read_secure_or_a_later_chapter() -> None:
    assert extract_title_num("Sec. 15-40. - Injunction.") == "15-40"
    assert extract_title_num("381.38 FAILURE TO SECURE DANGEROUS ORDNANCE") == "381.38"
    assert extract_title_num("353.03.2 RESERVATION OF PARKING SPACES") == "353.03.2"
    assert (
        extract_title_num(
            "186.04 GROUNDS FOR SUBSTANCE ABUSE TESTING NOT COVERED UNDER CHAPTER 180"
        )
        == "186.04"
    )
    assert extract_title_num("FAILURE TO SECURE DANGEROUS ORDNANCE") == ""
    assert extract_title_num("CHAPTER 186 GENERAL PROVISIONS") == ""
    assert extract_title_num("Secs. 2-7—2-30. - Reserved.") == "2-7—2-30"
    assert "URE" not in extract_title_num("381.38 FAILURE TO SECURE DANGEROUS ORDNANCE")


def test_ordinance_number_is_not_the_passage_date() -> None:
    parsed = parse_history_fields("Ord. 98-6-61. Passed 6-24-98.")
    assert parsed["date"] == "6-24-98"
    assert parsed["year"] == "1998"
    assert parsed["enacted"] == "1998"
    assert passage_dates("Ord. 98-6-61. Passed 6-24-98.") == [("6-24-98", "1998-06-24")]
    assert passage_dates("Passed 6-12-24.") == [("6-12-24", "2024-06-12")]
    assert passage_dates("Passed 7-25-07.") == [("7-25-07", "2007-07-25")]
    assert passage_dates("Passed 6-18-69.") == [("6-18-69", "1969-06-18")]
    assert passage_dates("Passed June 12, 2024.") == [("June 12, 2024", "2024-06-12")]
    both = passage_dates("Ord. 98-6-61. Passed 6-24-98; Ord. 2024-6-42. Passed 6-12-24.")
    assert both == [("6-24-98", "1998-06-24"), ("6-12-24", "2024-06-12")]
    assert parse_year("98-6-61") == ""
    assert parse_year("98") == ""
    assert parse_year("Ord. 98") == ""
    assert parse_year("6-24-98") == "1998"
    assert parse_year("2009-7-62") == ""
    assert passage_dates("Ord. 3570. Passed 12-16-36") == [("12-16-36", "1936-12-16")]
    assert passage_dates("Ord. 4935. Passed 1-19-49") == [("1-19-49", "1949-01-19")]
    assert passage_dates("Passed 12- 21-09.") == [("12- 21-09", "2009-12-21")]
    assert passage_dates("Passed 9-28-22.") == [("9-28-22", "2022-09-28")]
    old_and_new = passage_dates(
        "Ord. 4935. Passed 1-19-49; Ord. 2022-9-89. Passed 9-28-22."
    )
    assert old_and_new == [("1-19-49", "1949-01-19"), ("9-28-22", "2022-09-28")]
    assert max(iso for _raw, iso in old_and_new) == "2022-09-28"
    # Codepublishing notes put the date after a comma, with no "Passed".
    assert passage_dates("Ord. No. 75-02, 4-21-75") == [("4-21-75", "1975-04-21")]
    assert passage_dates("Ord. 679, 10-8-2018") == [("10-8-2018", "2018-10-08")]
    assert passage_dates("Amd. of 7-9-13") == [("7-9-13", "2013-07-09")]
    assert passage_dates("Ord. No. 0709-2023, § 1, 3-13-2023") == [
        ("3-13-2023", "2023-03-13")
    ]
    assert passage_dates("Ord. No. 98-6-61") == []
    assert passage_dates("Ord. No. 80-01, § 12-15-10") == []
    assert passage_dates("See § 12-15-10 for the map.") == []
    assert adoption_line_dates(
        "____________ Adopted: October 16, 1990 Effective: October 16, 1990 ____________"
    ) == [("October 16, 1990", "1990-10-16")]
    assert adoption_line_dates(
        "legislation current through Ordinance 764, passed 12-8-2025"
    ) == []
    assert adoption_line_dates(
        "amendatory ordinances adopted through September 17, 2018"
    ) == []
    assert adoption_line_dates(
        "Adopted: October 16, 1990. Ordinances adopted after January 1, 1990, "
        "that amend this Code."
    ) == [("October 16, 1990", "1990-10-16")]
    assert adoption_line_dates(
        "Ordinance No. Date Adopted Include/Omit Supp. No. Ord. of 11-16-10 Include"
    ) == []
    assert adoption_line_dates("Date Adopted: October 16, 1990") == [
        ("October 16, 1990", "1990-10-16")
    ]


def test_citation_rows_keep_the_leading_section_and_passage_year() -> None:
    rows = html_rows_to_citation_rows(
        [
            {
                "cid": "ch",
                "doc_id": "1",
                "doc_order": 1,
                "html_title": "CHAPTER 186 GENERAL PROVISIONS",
                "html": "<p></p>",
                "_title": "CHAPTER 186 GENERAL PROVISIONS",
            },
            {
                "cid": "sec",
                "doc_id": "2",
                "doc_order": 2,
                "html_title": "186.04 GROUNDS NOT COVERED UNDER CHAPTER 180",
                "html": "<p>(Ord. 98-6-61. Passed 6-24-98.)</p>",
                "_title": "186.04 GROUNDS NOT COVERED UNDER CHAPTER 180",
            },
            {
                "cid": "secure",
                "doc_id": "3",
                "doc_order": 3,
                "html_title": "381.38 FAILURE TO SECURE DANGEROUS ORDNANCE",
                "html": "<p>(Ord. 91-9-119. Passed 9-25-91.)</p>",
                "_title": "381.38 FAILURE TO SECURE DANGEROUS ORDNANCE",
            },
        ],
        place_name="City of Hamilton",
        state_code="OH",
    )
    by_cid = {row["cid"]: row for row in rows}
    assert by_cid["sec"]["title_num"] == "186.04"
    assert by_cid["sec"]["chapter_num"] == "186"
    assert by_cid["sec"]["date"] == "6-24-98"
    assert by_cid["sec"]["year"] == "1998"
    assert "§ 186.04" in by_cid["sec"]["bluebook_citation"]
    assert "(1998)" in by_cid["sec"]["bluebook_citation"]
    assert "1961" not in by_cid["sec"]["bluebook_citation"]
    assert "§ 180" not in by_cid["sec"]["bluebook_citation"]
    assert by_cid["secure"]["title_num"] == "381.38"
    assert "URE" not in by_cid["secure"]["bluebook_citation"]
    assert by_cid["ch"]["title_num"] == ""
    assert by_cid["ch"]["chapter_num"] == "186"


def test_history_notes_do_not_have_to_start_with_ord() -> None:
    cross = extract_history_notes(
        "<p>(1931 Code &#167; 14.3010; Ord. 2017-9-105. Passed 9-13-17.)</p>"
    )
    assert any("9-13-17" in note for note in cross)
    assert passage_dates(cross[-1]) == [("9-13-17", "2017-09-13")]
    emergency = extract_history_notes(
        "<p>(EOrd. 2019-12-138. Passed 12-11-19.)</p>"
    )
    assert passage_dates(emergency[0]) == [("12-11-19", "2019-12-11")]
    spaced = extract_history_notes(
        "<p>(Ord. 2009-12-121. Passed 12- 21-09.)</p>"
    )
    assert passage_dates(spaced[0]) == [("12- 21-09", "2009-12-21")]
    bare = extract_history_notes("<p>(Ord 84-12-108. Passed 12-27-84.)</p>")
    assert passage_dates(bare[0]) == [("12-27-84", "1984-12-27")]


def test_source_url_uses_canonical_or_municode_node_only() -> None:
    assert source_url_from_html(
        '<link rel="canonical" href="https://cityofcollins.com/documents/ordinance-530-noise/" />'
        '<a href="https://fonts.googleapis.com/css?family=Lato">x</a>'
    ) == "https://cityofcollins.com/documents/ordinance-530-noise/"
    assert source_url_from_html(
        '<a href="/codes/hamilton/latest/hamilton_oh/0-0-0-23807">186.04</a>'
        '<a href="/codes/hamilton/latest/hamilton_oh/0-0-0-99999">other</a>'
    ) == "https://library.municode.com/codes/hamilton/latest/hamilton_oh/0-0-0-23807"
    assert source_url_from_html(
        '<a href="http://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=GOV">x</a>'
        '<a href="/CA/Holtville">Holtville</a>'
    ) is None
    assert source_url_from_html('<a href="https://codelibrary.amlegal.com/">home</a>') is None
    assert source_url_from_html("") is None
