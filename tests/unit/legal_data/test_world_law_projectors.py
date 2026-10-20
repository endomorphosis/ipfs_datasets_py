"""Sealed one-row projections into legal-record/v1. No Hub download."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_scrapers.world_law.load_sharded_laws import (
    load_sharded_laws,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    expand_legal_record,
    render_atomic,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_american_municipal_row import (
    chapter_after,
    heading_after,
    origin_urls_from_html,
    place_from_gnis,
    place_from_origin_urls,
    place_from_titles,
    project_american_municipal_row,
    resolve_place,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_html_municipal_row import (
    project_html_municipal_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_world_v11_row import (
    project_world_v11_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import LEGAL_RECORD_FIELDS

_SHA = "a" * 40


def _html_row(country: str) -> dict[str, object]:
    return {
        "cid": "bafy-html",
        "jurisdiction_id": "place-1",
        "jurisdiction_name": "Halifax",
        "country": country,
        "doc_id": "doc-1",
        "regeling_id": "reg-1",
        "regeling_work_id": "work-1",
        "doc_order": 1,
        "title": None,
        "structural_path": "bylaw/1",
        "node_label": "section",
        "html_title": '<div class="chunk-title">Far North</div>',
        "html": "<html><body>secret</body></html>",
        "text": "Bylaw text",
        "source_url": "https://example.test/bylaw",
        "xml_url": None,
        "date_effective": "2022-01-03",
        "date_modified": "2022-02-01",
        "retrieved": "2026-10-13",
    }


def test_html_municipal_keeps_a_row_without_source_policy() -> None:
    record = project_html_municipal_row(
        _html_row("Canada"),
        source_repo="endomorphosis/ipfs_canada_municipal_laws",
        source_revision=_SHA,
    )
    assert record is not None
    assert list(record) == list(LEGAL_RECORD_FIELDS)
    assert record["jurisdiction"] == "CA"
    assert record["title"] == "Far North"
    assert record["effective_date"] == "2022-01-03"
    assert record["authority"] == "Halifax"
    assert record["text"] == "Bylaw text"
    assert "<" not in str(record["title"])
    assert "<html" not in str(record["text"]).casefold()
    assert "html" not in record
    assert record["normalizer_version"] == "html-municipal-scraper/v1+legal-record/v1"
    assert record["provenance"]["source_policy"] is None
    assert record["provenance"]["content_complete"] is True
    assert record["provenance"]["regeling_id"] == "reg-1"


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("NZ", "NZ"),
        ("BE", "BE"),
        ("ID", "ID"),
        ("PT", "PT"),
        ("new zealand", "NZ"),
    ],
)
def test_html_country_fold(country: str, expected: str) -> None:
    record = project_html_municipal_row(
        _html_row(country),
        source_repo="endomorphosis/ipfs_example_municipal_laws",
        source_revision=_SHA,
    )
    assert record is not None
    assert record["jurisdiction"] == expected


def test_html_null_text_is_kept_when_html_is_null_or_absent() -> None:
    both_null = _html_row("Canada")
    both_null["text"] = None
    both_null["html"] = None
    missing = _html_row("Canada")
    missing["text"] = None
    del missing["html"]
    for row in (both_null, missing):
        record = project_html_municipal_row(
            row,
            source_repo="endomorphosis/ipfs_canada_municipal_laws",
            source_revision=_SHA,
        )
        assert record is not None
        assert record["text"] is None
        assert record["provenance"]["content_complete"] is False
        assert "html" not in record


def test_html_equal_non_null_strings_still_raise() -> None:
    row = _html_row("Canada")
    row["text"] = "<p>same</p>"
    row["html"] = "<p>same</p>"
    with pytest.raises(RuntimeError, match="html must not be copied"):
        project_html_municipal_row(
            row,
            source_repo="endomorphosis/ipfs_canada_municipal_laws",
            source_revision=_SHA,
        )


def test_html_unknown_country_is_dropped() -> None:
    assert (
        project_html_municipal_row(
            _html_row("Narnia"),
            source_repo="endomorphosis/ipfs_example_municipal_laws",
            source_revision=_SHA,
        )
        is None
    )


def test_american_municipal_keeps_plain_text_and_section_locator() -> None:
    record = project_american_municipal_row(
        {
            "cid": "bafy-us",
            "doc_id": "d1",
            "doc_order": 3,
            "html_title": '<div class="chunk-title">Sec. 15-40. - Injunction.</div>',
            "html": (
                '<div class="chunk-content"><p>The city may seek an injunction (this) year.</p>'
                "<p>(a) Notice is required before the hearing.</p></div>"
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    assert record["jurisdiction"] is None
    assert record["admin_level"] == "us-municipal"
    assert record["instrument_type"] == "ordinance"
    assert record["citation"] is None
    assert record["bluebook_citation"] is None
    assert record["language"] is None
    assert record["authority"] is None
    assert record["source_url"] is None
    assert record["published_date"] is None
    assert record["effective_date"] is None
    assert record["title"] == "Sec. 15-40. - Injunction."
    assert record["text"] == (
        "The city may seek an injunction (this) year.\n\n"
        "(a) Notice is required before the hearing."
    )
    assert "<" not in str(record["text"])
    assert record["content_sha256"]
    assert record["provenance"]["content_complete"] is True
    assert record["provenance"]["section"] == "15-40"
    assert record["provenance"]["hierarchy_path"] == "Section 15-40"
    assert "html" not in record
    assert record["normalizer_version"] == "american-municipal-html/v4+legal-record/v1"
    atoms = expand_legal_record(record)
    assert len(atoms) == 1
    document = render_atomic(atoms[0], "jsonld")
    assert document["@type"] == "Legislation"
    assert document["encodingFormat"] == "text/plain"
    assert "injunction" in str(document["text"])
    assert document["name"] == "Sec. 15-40. - Injunction."
    properties = {
        item["propertyID"]: item["value"] for item in document["additionalProperty"]
    }
    assert properties["section"] == "15-40"
    assert properties["subsection"] == "a"
    assert properties["atomic"] == "true"
    assert "<" not in document["text"]


def test_american_municipal_empty_html_stays_null() -> None:
    record = project_american_municipal_row(
        {
            "cid": "bafy-empty",
            "doc_id": "d2",
            "doc_order": 1,
            "html_title": '<div class="chunk-title">Chapter 18 - COURTS</div>',
            "html": '<div class="chunk-content"></div>',
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    assert record["text"] is None
    assert record["content_sha256"] is None
    assert record["jurisdiction"] is None
    assert record["published_date"] is None
    assert record["provenance"]["content_complete"] is False
    assert record["provenance"]["chapter"] == "18"
    assert "section" not in record["provenance"]
    kept = project_american_municipal_row(
        {
            "cid": "bafy-lt",
            "doc_id": "d3",
            "doc_order": 2,
            "html_title": "Setback",
            "html": "<p>The setback shall be &lt; 10 feet from the lot line.</p>",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    assert kept["text"] == "The setback shall be < 10 feet from the lot line."
    broken = project_american_municipal_row(
        {
            "cid": "bafy-broken",
            "doc_id": "d4",
            "doc_order": 4,
            "html_title": "Broken",
            "html": "<p>See <div the rest of the ordinance",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    assert broken["text"] is None
    assert broken["provenance"]["content_complete"] is False


def test_american_municipal_citation_uses_place_and_passage_date() -> None:
    record = project_american_municipal_row(
        {
            "cid": "bafy-ham",
            "doc_id": "186.04",
            "doc_order": 4,
            "html_title": (
                "186.04 GROUNDS FOR SUBSTANCE ABUSE TESTING NOT COVERED UNDER CHAPTER 180"
            ),
            "html": (
                "<p>Testing under this section is limited.</p>"
                "<p>(Ord. 98-6-61. Passed 6-24-98.)</p>"
                '<p><a href="/codes/hamilton/latest/hamilton_oh/0-0-0-23807">186.04</a></p>'
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Hamilton",
        state_code="oh",
        chapter_num="186",
    )
    assert record["jurisdiction"] == "US-OH"
    assert record["authority"] == "City of Hamilton"
    assert record["language"] == "en"
    assert record["published_date"] is None
    assert record["effective_date"] == "1998-06-24"
    assert record["source_url"] == (
        "https://library.municode.com/codes/hamilton/latest/hamilton_oh/0-0-0-23807"
    )
    assert record["provenance"]["section"] == "186.04"
    assert record["provenance"]["chapter"] == "186"
    assert "180" != record["provenance"]["section"]
    cite = str(record["bluebook_citation"])
    assert cite == record["citation"]
    assert "§ 186.04" in cite
    assert "(1998)" in cite
    assert "1961" not in cite
    assert "URE" not in cite
    assert "§ 180" not in cite
    assert record["text"] == "Testing under this section is limited.\n\n(Ord. 98-6-61. Passed 6-24-98.)\n\n186.04"
    assert "<" not in str(record["text"])
    document = render_atomic(record, "jsonld")
    assert document["@type"] == "Legislation"
    assert document["legislationJurisdiction"] == "US-OH"
    assert document["legislationIdentifier"] == cite
    assert document["inLanguage"] == "en"
    assert document["legislationDate"] == "1998-06-24"
    assert document["url"] == record["source_url"]
    assert "datePublished" not in document
    assert "dateModified" not in document
    properties = {item["propertyID"]: item["value"] for item in document["additionalProperty"]}
    assert properties["section"] == "186.04"
    assert properties["chapter"] == "186"
    assert properties["bluebook_citation"] == cite
    assert properties["authority"] == "City of Hamilton"
    assert "1961" not in json.dumps(document)


def test_american_municipal_rejects_secure_and_cross_chapter_as_section() -> None:
    secure = project_american_municipal_row(
        {
            "cid": "bafy-secure",
            "doc_id": "381.38",
            "doc_order": 8,
            "html_title": "381.38 FAILURE TO SECURE DANGEROUS ORDNANCE",
            "html": "<p>No person shall fail to secure a dangerous ordnance.</p>",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Hamilton",
        state_code="OH",
    )
    assert secure["provenance"]["section"] == "381.38"
    assert "URE" not in str(secure["bluebook_citation"])
    assert "§ 381.38" in str(secure["bluebook_citation"])
    crossed = project_american_municipal_row(
        {
            "cid": "bafy-cross",
            "doc_id": "186.04",
            "doc_order": 9,
            "html_title": "186.04 GROUNDS NOT COVERED UNDER CHAPTER 180",
            "html": "<p>The grounds are stated here.</p>",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Hamilton",
        state_code="OH",
    )
    assert crossed["provenance"]["section"] == "186.04"
    assert "chapter" not in crossed["provenance"]
    assert "§ 180" not in str(crossed["bluebook_citation"])
    unknown = project_american_municipal_row(
        {
            "cid": "bafy-xx",
            "doc_id": "1",
            "doc_order": 1,
            "html_title": "Sec. 1. - Name.",
            "html": "<p>The name is the city.</p>",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="Example City",
        state_code="ZZ",
    )
    assert unknown["jurisdiction"] is None
    assert unknown["language"] is None
    assert unknown["citation"] is None
    assert unknown["authority"] == "Example City"
    reserved = project_american_municipal_row(
        {
            "cid": "bafy-reserved",
            "doc_id": "2-7",
            "doc_order": 2,
            "html_title": "Secs. 2-7—2-30. - Reserved.",
            "html": "<p>Reserved.</p>",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Orange Park",
        state_code="FL",
    )
    assert reserved["provenance"]["section"] == "2-7—2-30"
    assert "§ 2-7—2-30" in str(reserved["bluebook_citation"])


def test_american_municipal_source_url_skips_chrome_and_cross_references() -> None:
    canonical = project_american_municipal_row(
        {
            "cid": "bafy-canon",
            "doc_id": "530",
            "doc_order": 2,
            "html_title": "Ordinance 530- Noise – City of Collins",
            "html": (
                '<link rel="canonical" href="https://cityofcollins.com/documents/ordinance-530-noise/" />'
                '<a href="https://fonts.googleapis.com/css?family=Lato">font</a>'
                "<p>Quiet hours apply.</p>"
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Collins",
        state_code="IA",
    )
    assert canonical["source_url"] == "https://cityofcollins.com/documents/ordinance-530-noise/"
    cross = project_american_municipal_row(
        {
            "cid": "bafy-holt",
            "doc_id": "1.02.010",
            "doc_order": 11,
            "html_title": "1.02.010 Date of general municipal election.",
            "html": (
                '<a href="http://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml'
                '?lawCode=GOV&sectionNum=36503.5">Gov</a>'
                '<a href="/CA/Holtville">Holtville</a>'
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Holtville",
        state_code="CA",
    )
    assert cross["source_url"] is None
    assert cross["jurisdiction"] == "US-CA"
    assert cross["provenance"]["section"] == "1.02.010"
    latest = project_american_municipal_row(
        {
            "cid": "bafy-two",
            "doc_id": "3",
            "doc_order": 3,
            "html_title": "3.02 Election, Term, Vacancies.",
            "html": (
                "<p>(Ord. 98-6-61. Passed 6-24-98; Ord. 2024-6-42. Passed 6-12-24.)</p>"
                "<p>The term is four years.</p>"
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Hamilton",
        state_code="OH",
    )
    assert latest["effective_date"] == "2024-06-12"
    assert "(2024)" in str(latest["bluebook_citation"])
    assert "1961" not in str(latest["bluebook_citation"])
    assert latest["provenance"]["passage_dates"] == ["1998-06-24", "2024-06-12"]
    early = project_american_municipal_row(
        {
            "cid": "bafy-1949",
            "doc_id": "509.08",
            "doc_order": 4,
            "html_title": "509.08 OTHER FALSE CALLS.",
            "html": (
                "<p>(Ord. 4935. Passed 1-19-49; Ord. 2022-9-89. Passed 9-28-22.)</p>"
                "<p>A false call is prohibited.</p>"
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Hamilton",
        state_code="OH",
    )
    assert early["effective_date"] == "2022-09-28"
    assert "(2022)" in str(early["bluebook_citation"])
    assert "2049" not in str(early["bluebook_citation"])
    assert early["provenance"]["passage_dates"] == ["1949-01-19", "2022-09-28"]
    comma_date = project_american_municipal_row(
        {
            "cid": "bafy-comma",
            "doc_id": "1-5",
            "doc_order": 5,
            "html_title": "Sec. 1-5. - Code does not affect prior offenses.",
            "html": (
                "<div>current through Ordinance 764, passed 12-8-2025</div>"
                "<p>(Ord. No. 75-02, 4-21-75.)</p>"
                "<p>Prior offenses stay governed by the law then in force.</p>"
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="Cleveland County",
        state_code="NC",
    )
    assert comma_date["effective_date"] == "1975-04-21"
    assert comma_date["provenance"]["passage_dates"] == ["1975-04-21"]
    assert "(1975)" in str(comma_date["bluebook_citation"])
    assert "2025" not in str(comma_date["bluebook_citation"])
    adopted = project_american_municipal_row(
        {
            "cid": "bafy-adopted",
            "doc_id": "code",
            "doc_order": 1,
            "html_title": "CODE OF ORDINANCES - CLEVELAND COUNTY, NORTH CAROLINA",
            "html": (
                "<p>____________ Adopted: October 16, 1990 "
                "Effective: October 16, 1990 ____________</p>"
            ),
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="Cleveland County",
        state_code="NC",
    )
    assert adopted["effective_date"] == "1990-10-16"
    assert adopted["provenance"]["passage_dates"] == ["1990-10-16"]
    currency = project_american_municipal_row(
        {
            "cid": "bafy-currency",
            "doc_id": "title",
            "doc_order": 1,
            "html_title": "FOREST LAKE, MINNESOTA CODE OF ORDINANCES",
            "html": "<p>legislation current through Ordinance 764, passed 12-8-2025</p>",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Forest Lake",
        state_code="MN",
    )
    assert currency["effective_date"] is None
    assert currency["published_date"] is None


def _world_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "cid": "bafy-world",
        "country_code": "FR",
        "doc_type": "statute",
        "title_native": "Code civil",
        "number": "Art. 1",
        "text": "Les lois",
        "content_complete": True,
        "source_policy": None,
        "source_official": True,
        "source_url": "https://example.test/fr",
        "language": "fr",
    }
    row.update(overrides)
    return row


def test_world_projector_drops_archived_and_unofficial_rows() -> None:
    kept = project_world_v11_row(
        _world_row(),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert kept is not None
    assert kept["text"] == "Les lois"
    assert kept["citation"] == "Art. 1"
    assert kept["bluebook_citation"] is None
    assert kept["normalizer_version"] == "world-law/v1.1.0+legal-record/v1"
    assert "html" not in kept

    archived = project_world_v11_row(
        _world_row(source_policy="archived_robots_disallowed"),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    unofficial = project_world_v11_row(
        _world_row(source_official=False),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    omitted = project_world_v11_row(
        _world_row(country_code="US"),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
        drop_us=True,
    )
    assert archived is None
    assert unofficial is None
    assert omitted is None


def test_world_national_stays_country_and_municipal_is_municipality() -> None:
    national = project_world_v11_row(
        _world_row(),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    municipal = project_world_v11_row(
        _world_row(country_code="ES", doc_type="ordinance"),
        source_repo="endomorphosis/world_municipal_law",
        source_revision=_SHA,
        admin_level="municipality",
    )
    assert national is not None and municipal is not None
    assert national["admin_level"] == "country"
    assert municipal["admin_level"] == "municipality"
    assert municipal["jurisdiction"] == "ES"
    assert "html" not in national
    assert "html" not in municipal


def test_world_incomplete_text_is_null() -> None:
    record = project_world_v11_row(
        _world_row(content_complete=False, text="<html><body>hidden</body></html>"),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert record is not None
    assert record["text"] is None
    assert record["provenance"]["content_complete"] is False


def test_load_sharded_laws_writes_laws_and_rejects_a_short_revision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data = source / "data"
    data.mkdir(parents=True)
    pq.write_table(pa.table({"id": ["a"], "text": ["one"]}), data / "laws-00001.parquet")
    pq.write_table(pa.table({"id": ["b"], "text": ["two"]}), data / "laws-00002.parquet")
    pq.write_table(pa.table({"id": ["html"], "text": ["skip"]}), data / "laws-00003_html.parquet")
    pq.write_table(pa.table({"article": ["1"]}), data / "articles-00001.parquet")
    with pytest.raises(ValueError):
        load_sharded_laws(
            source,
            tmp_path / "bad",
            slug="spain_municipal",
            source_dataset="endomorphosis/ipfs_spain_municipal_laws",
            source_revision="not-a-sha",
        )
    dest = tmp_path / "packed"
    written = load_sharded_laws(
        source,
        dest,
        slug="spain_municipal",
        source_dataset="endomorphosis/ipfs_spain_municipal_laws",
        source_revision=_SHA,
    )
    laws = pq.read_table(written["laws"])
    assert laws.column("id").to_pylist() == ["a", "b"]
    assert Path(written["articles"]).is_file()
    meta = json.loads((dest / "pack_meta.json").read_text(encoding="utf-8"))
    assert meta["source_revision"] == _SHA
    assert meta["slug"] == "spain_municipal"


def _american_row(cid: str, title: str, html: str = "<p>The rule is stated here.</p>") -> dict[str, object]:
    return {
        "cid": cid,
        "doc_id": cid,
        "doc_order": 1,
        "html_title": title,
        "html": html,
    }


def test_heading_stack_inherits_and_a_new_chapter_clears_nested_headings() -> None:
    stack: tuple[tuple[str, str], ...] = ()
    for title in (
        "Title 1 General",
        "Chapter 1 Animals",
        "Article III Dogs",
        "Division A Licenses",
        "Part 1 Fees",
    ):
        stack = heading_after(title, stack)
    assert stack == (
        ("title", "1"),
        ("chapter", "1"),
        ("article", "III"),
        ("division", "A"),
        ("part", "1"),
    )
    record = project_american_municipal_row(
        _american_row("sec", "Sec. 2-1. Licenses."),
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        place_name="City of Ely",
        state_code="MN",
        heading_stack=stack,
    )
    provenance = record["provenance"]
    assert provenance["title"] == "1"
    assert provenance["chapter"] == "1"
    assert provenance["article"] == "III"
    assert provenance["division"] == "A"
    assert provenance["part"] == "1"
    assert provenance["section"] == "2-1"
    assert "statute" not in provenance
    assert provenance["hierarchy_path"] == (
        "Title 1 / Chapter 1 / Article III / Division A / Part 1 / Section 2-1"
    )
    atoms = expand_legal_record(record)
    assert len(atoms) == 1
    assert atoms[0]["provenance"]["article"] == "III"
    assert atoms[0]["provenance"]["division"] == "A"
    assert atoms[0]["provenance"]["statute"] == record["citation"]
    document = render_atomic(atoms[0], "jsonld")
    properties = {item["propertyID"]: item["value"] for item in document["additionalProperty"]}
    assert properties["article"] == "III"
    assert properties["division"] == "A"
    assert properties["chapter"] == "1"
    assert properties["section"] == "2-1"
    cleared = heading_after("Chapter 2 Nuisances", stack)
    assert cleared == (("title", "1"), ("chapter", "2"))
    after = project_american_municipal_row(
        _american_row("noise", "Sec. 2-2. Noise."),
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        heading_stack=cleared,
    )
    assert after["provenance"]["chapter"] == "2"
    assert after["provenance"]["title"] == "1"
    assert "article" not in after["provenance"]
    assert "division" not in after["provenance"]
    assert "part" not in after["provenance"]
    assert after["provenance"]["section"] == "2-2"


def test_part_then_article_then_a_new_part_clears_the_article() -> None:
    stack: tuple[tuple[str, str], ...] = ()
    stack = heading_after("Chapter 1", stack)
    stack = heading_after("Part 1", stack)
    stack = heading_after("Article II", stack)
    assert stack == (("chapter", "1"), ("part", "1"), ("article", "II"))
    stack = heading_after("Part 2", stack)
    assert stack == (("chapter", "1"), ("part", "2"))
    assert heading_after("Division of Fire Prevention", stack) == stack
    assert chapter_after("186.04 GROUNDS NOT COVERED UNDER CHAPTER 180", "186") == "186"
    assert chapter_after("CHAPTER 2 GENERAL", "186") == "2"
    assert chapter_after("381.38 FAILURE TO SECURE DANGEROUS ORDNANCE", "186") == "186"


def test_article_heading_keeps_statute_and_a_cross_chapter_does_not_stick() -> None:
    article = project_american_municipal_row(
        _american_row("art", "ARTICLE 1. - Jurisdiction", "<div></div>"),
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        heading_stack=(("chapter", "4"),),
    )
    assert article["provenance"]["chapter"] == "4"
    assert article["provenance"]["article"] == "1"
    assert article["provenance"]["statute"] == "1"
    assert article["provenance"]["hierarchy_path"] == "Chapter 4 / Article 1"
    assert "section" not in article["provenance"]
    crossed = project_american_municipal_row(
        _american_row("cross", "186.04 GROUNDS NOT COVERED UNDER CHAPTER 180"),
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
        heading_stack=(("chapter", "186"), ("article", "II")),
    )
    assert crossed["provenance"]["chapter"] == "186"
    assert crossed["provenance"]["article"] == "II"
    assert crossed["provenance"]["section"] == "186.04"
    assert "180" != crossed["provenance"]["chapter"]


def test_place_from_titles_recovers_one_pair_and_leaves_the_rest_unset() -> None:
    assert place_from_titles(["Ordinances - Howard, SD"]) == ("Howard", "SD")
    assert place_from_titles(
        ["Ordinance Code, Permits & Licenses - St. Croix Falls, Wisconsin"]
    ) == ("St. Croix Falls", "WI")
    assert place_from_titles(
        [
            "City of Ely Charter - City of Ely, MN",
            "City Code & Ordinances - Ely, MN",
        ]
    ) == ("City of Ely", "MN")
    assert place_from_titles(["City of Stratford,   Iowa"]) == ("City of Stratford", "IA")
    assert place_from_titles(
        [
            "Municipal Codes - City of Griggsville",
            "Griggsville Illinois Fire Contact Information",
        ]
    ) == ("City of Griggsville", "IL")
    assert place_from_titles(["City of Graham  Georgia"]) == ("City of Graham", "GA")
    assert place_from_titles(["City of Bluefield, West Virginia"]) == ("City of Bluefield", "WV")
    assert place_from_titles(["Ordinances | City of Wendell"]) is None
    assert place_from_titles(["City of Des Arc"]) is None
    assert place_from_titles(["City of Three Way"]) is None
    assert place_from_titles(["ARTICLE I TOWN OF MUSCATINE CREATED A CITY"]) is None
    assert place_from_titles(["Object moved"]) is None
    assert place_from_titles(["Parking Along Virginia"]) is None
    assert place_from_titles(["Code of Virginia"]) is None
    assert place_from_titles(["CODE, IN THE BOOK"]) is None
    assert place_from_titles(["CODE, INFORMATION"]) is None
    assert place_from_titles(["Welcome to Amidon, North Dakota!"]) == ("Amidon", "ND")
    assert place_from_titles(["Best Local Eateries and Shops in Colo, Iowa"]) == ("Colo", "IA")
    assert place_from_titles(["The Official Site of Centreville, Alabama"]) == ("Centreville", "AL")
    assert place_from_titles(["THE CODE OF CARNESVILLE, GEORGIA"]) == ("CARNESVILLE", "GA")
    assert place_from_titles(
        ["News - Mineral Point Chamber of Commerce, WI"]
    ) == ("Mineral Point", "WI")
    assert place_from_titles(["City Ordinances | City of Wisconsin dells"]) == (
        "City of Wisconsin dells",
        "WI",
    )
    assert place_from_titles(["City of Wyoming (IL)"]) == ("City of Wyoming", "IL")
    assert place_from_titles(["Coon Rapids - One of Iowa's Great Places"]) is None
    assert place_from_titles(
        ["Crossing yellow pavement marking on West Pennsylvania Avenue."]
    ) is None
    assert place_from_titles(
        [
            "Development Restrictions In Section 24, Township 10 North, "
            "Range 3 West Of The I.M., Moore, Cleveland County, Oklahoma"
        ]
    ) is None
    assert place_from_titles(
        ["Ordinances – City of Augusta, Eau Claire County, WI"]
    ) == ("City of Augusta", "WI")
    assert place_from_titles(
        ["Ordinances & Resolutions - WELCOME TO ADAMS, OREGON"]
    ) == ("ADAMS", "OR")
    assert place_from_titles(
        ["Adoption Of Misdemeanor Provisions Utah State Criminal Code"]
    ) is None
    assert place_from_titles(["City of Ely, MN", "City of Two Harbors, MN"]) is None
    assert place_from_titles(["City of Ely, MN", "Town of Ely, MN"]) is None
    assert place_from_titles(["Howard, SD", "Howard, MN"]) is None
    assert resolve_place("City of Hamilton", "OH", ["City of Ely, MN"]) == (
        "City of Hamilton",
        "OH",
    )
    assert resolve_place("", "", ["City of Ely, MN"]) == ("City of Ely", "MN")
    assert resolve_place("City of Wendell", "", ["City of Ely, MN"]) == ("City of Wendell", None)
    assert resolve_place("", "OH", ["City of Ely, MN"]) == (None, "OH")


def test_place_from_origin_url_uses_the_page_url_only() -> None:
    assert place_from_origin_urls(["https://www.jetmorekansas.com/"]) == ("Jetmore", "KS")
    assert place_from_origin_urls(["https://www.owasaiowa.com/news"]) == ("Owasa", "IA")
    assert place_from_origin_urls(["https://www.cityofioneoregon.com/"]) == ("City of Ione", "OR")
    assert place_from_origin_urls(["https://goshenindiana.org/"]) == ("Goshen", "IN")
    assert place_from_origin_urls(["https://www.colma.ca.gov/municipal-code"]) == ("Colma", "CA")
    assert place_from_origin_urls(["https://ci.richmond.mn.us/"]) == ("Richmond", "MN")
    assert place_from_origin_urls(["https://caguas.gov.pr/"]) == ("Caguas", "PR")
    assert place_from_origin_urls(["https://cityofwrightsville-ar.org/"]) == (
        "City of Wrightsville",
        "AR",
    )
    assert place_from_origin_urls(["https://windom-mn.com/"]) == ("Windom", "MN")
    assert place_from_origin_urls(["https://citykankakee-il.gov/"]) == ("Citykankakee", "IL")
    assert place_from_origin_urls(
        ["https://www.codepublishing.com/AZ/Flagstaff/html/Flagstaff10.html"]
    ) == ("Flagstaff", "AZ")
    assert place_from_origin_urls(
        ["https://library.municode.com/ca/los_angeles_county/codes/code_of_ordinances"]
    ) == ("Los Angeles County", "CA")
    assert place_from_origin_urls(
        ["https://online.encodeplus.com/regs/littleton-co-cc/index.aspx"]
    ) == ("Littleton", "CO")
    assert place_from_origin_urls(
        ["https://municipal.codes/wa/seattle/latest"]
    ) == ("Seattle", "WA")
    assert place_from_origin_urls(["https://www.cityofhelena.org/"]) is None
    assert place_from_origin_urls(["https://www.sandiego.gov/"]) is None
    assert place_from_origin_urls(["https://cityofhallsvilletx.com/ordinances"]) is None
    assert place_from_origin_urls(["https://www.cityoftacoma.org/code"]) is None
    assert place_from_origin_urls(["https://www.cityofarkadelphia.com/"]) is None
    assert place_from_origin_urls(["https://www.cityofbolivar.com/"]) is None
    assert place_from_origin_urls(["https://www.cityofdelphi.org/"]) is None
    assert place_from_origin_urls(["https://www.cityofwestpeoria.org/"]) is None
    assert place_from_origin_urls(["https://cityofnatoma.com/"]) is None
    assert place_from_origin_urls(["https://cityofkenova.com/"]) is None
    assert place_from_origin_urls(["https://osse.dc.gov/publication/code"]) is None
    assert place_from_origin_urls(["https://mayor.dc.gov/release/code"]) is None
    assert place_from_origin_urls(["https://portland.org/"]) is None
    assert place_from_origin_urls(["https://www.littletonco.gov/"]) is None
    assert place_from_origin_urls(["https://woburnma.gov/"]) is None
    assert place_from_origin_urls(["https://jamestowntn.gov/"]) is None
    assert place_from_origin_urls(["https://leonardnd.com/"]) is None
    assert place_from_origin_urls(["https://bluegrassia.org/"]) is None
    assert place_from_origin_urls(["https://montrealwis.com/"]) is None
    assert place_from_origin_urls(["https://municipal.codes/WA/RCW/35.21"]) is None
    assert place_from_origin_urls(["https://municipal.codes/WA/WAC/"]) is None
    assert place_from_origin_urls(["https://s3-us-west-2.amazonaws.com/bucket"]) is None
    assert place_from_origin_urls(
        ["https://www.facebook.com/cityofhallsvilletx"]
    ) is None
    assert place_from_origin_urls(
        ["https://codelibrary.amlegal.com/codes/lasalleil/latest/overview"]
    ) is None
    assert place_from_origin_urls(
        ["https://codelibrary.amlegal.com/codes/beachwood/latest/overview"]
    ) is None
    assert place_from_origin_urls(
        ["https://online.encodeplus.com/regs/board-or-commission/index.aspx"]
    ) is None
    assert place_from_origin_urls(
        [
            "https://www.jetmorekansas.com/",
            "https://www.colma.ca.gov/",
        ]
    ) is None
    page = (
        "<link rel='canonical' href='https://www.colma.ca.gov/municipal-code'>"
        "<a href='https://municipal.codes/WA/RCW/35.21'>RCW</a>"
        "<meta property='og:url' content='https://www.colma.ca.gov/municipal-code'>"
    )
    assert origin_urls_from_html(page) == ["https://www.colma.ca.gov/municipal-code"]
    assert resolve_place(
        "City of Hamilton",
        "OH",
        [],
        ["https://www.colma.ca.gov/"],
    ) == ("City of Hamilton", "OH")
    assert resolve_place(
        "",
        "",
        ["Object moved"],
        ["https://cityofhallsvilletx.com/"],
    ) == (None, None)
    assert resolve_place(
        "",
        "",
        ["Object moved"],
        ["https://www.jetmorekansas.com/"],
    ) == ("Jetmore", "KS")
    assert resolve_place(
        "",
        "",
        ["City of Ely, MN"],
        ["https://www.colma.ca.gov/"],
    ) == ("City of Ely", "MN")
    assert resolve_place("City of Wendell", "", [], ["https://www.colma.ca.gov/"]) == (
        "City of Wendell",
        None,
    )
    assert place_from_gnis("2395220") == ("City of New York", "NY")
    assert place_from_gnis("2411565") == ("City of La Cañada Flintridge", "CA")
    assert place_from_gnis("not-a-gnis") is None
    assert resolve_place("", "", ["City of Ely, MN"], gnis="2395220") == (
        "City of New York",
        "NY",
    )
    assert resolve_place("City of Hamilton", "OH", [], gnis="2395220") == (
        "City of Hamilton",
        "OH",
    )
    assert resolve_place("", "", ["City of Ely, MN"], gnis="not-a-gnis") == (
        "City of Ely",
        "MN",
    )
