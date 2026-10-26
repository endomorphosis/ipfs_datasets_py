"""Headings come from source context. A site name is not a section number."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.admit import (
    admit_source_law,
    fill_country_parquet,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
    assign_heading,
)

_SHA = "c" * 40
_ACT = (
    "Article 1 This Act applies throughout the territory.\n"
    "Article 2 The minister shall keep the register.\n"
)
_SHALL = (
    "The minister shall keep the register and apply this Act throughout the territory "
    "to every person who resides there."
)


def _located(row: dict[str, object]) -> dict[str, str]:
    decision = admit_source_law(
        row,
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    provenance = decision.records[0]["provenance"]
    assert isinstance(provenance, dict)
    return provenance


def _law(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "row-1",
        "title": "Payment terms",
        "text": _SHALL,
        "language": "en",
        "jurisdiction": "FR",
        "country": "France",
        "source_url": "",
        "metadata_json": "{}",
    }
    row.update(overrides)
    return row


def test_source_hierarchy_section_is_the_heading() -> None:
    found = assign_heading(
        {
            "title": "§ 1. Lønnen udbetales hver måned efter denne lov.",
            "article_number": "§ 1",
            "section_number": "1",
            "hierarchy_kind": "section",
            "hierarchy_path": "Section 1",
            "instrument_title": "Lov om løn",
            "source_type": "retsinformation",
            "official_citation": "lta/1905/67, art. § 1",
        }
    )
    assert found.status == "structural"
    assert found.evidence == "source_hierarchy"
    assert found.locator_map() == {"section": "1"}
    assert found.site == "retsinformation"
    assert found.site_from == "source_type"
    assert found.instrument == "Lov om løn"
    assert found.hierarchy_path == "Section 1"


def test_title_patterns_assign_the_provision_they_name() -> None:
    section = assign_heading({"title": "§ 4. Wages", "statute": "4", "citation": "4"})
    assert section.locator_map() == {"section": "4"}
    assert section.evidence == "title"
    article = assign_heading({"title": "Article 2", "statute": "2"})
    assert article.locator_map() == {"article": "2", "section": "2"}
    assert article.hierarchy_path == "Article 2"
    english = assign_heading({"title": "Section 9"})
    assert english.locator_map() == {"section": "9"}
    decimal = assign_heading({"title": "6.1 Reasons for declining to act on request"})
    assert decimal.locator_map()["section"] == "6.1"
    marginal = assign_heading({"title": "2A Binding the Crown", "statute": "Act 2/1901"})
    assert marginal.locator_map() == {"section": "2A"}
    assert marginal.instrument == "Act 2/1901"
    dotted = assign_heading({"title": "2. Application."})
    assert dotted.locator_map() == {"section": "2"}
    thai = assign_heading({"title": "มาตรา ๒๒"})
    assert thai.locator_map()["article"] == "22"
    part = assign_heading(
        {"title": "TREATY ESTABLISHING THE EUROPEAN ECONOMIC COMMUNITY, PART TWO"}
    )
    assert part.locator_map() == {"part": "2"}
    assert part.instrument.startswith("TREATY ESTABLISHING")


def test_a_bare_citation_is_not_a_section_and_a_title_wins_a_disagreement() -> None:
    treaty = assign_heading(
        {
            "title": "Genfer Abkommen über die Behandlung der Kriegsgefangenen",
            "statute": "1",
            "citation": "1",
        }
    )
    assert treaty.status == "instrument_only"
    assert treaty.locators == ()
    assert "Abkommen" in treaty.instrument
    disagreed = assign_heading({"title": "Article 2", "article_number": "5", "statute": "5"})
    assert disagreed.locator_map() == {"article": "2", "section": "2"}
    assert disagreed.evidence == "title"
    hierarchy = assign_heading(
        {
            "title": "Article 9",
            "hierarchy_kind": "section",
            "section_number": "4",
        }
    )
    assert hierarchy.evidence == "source_hierarchy"
    assert hierarchy.locator_map() == {"section": "4"}


def test_a_source_url_can_name_the_section_and_the_site_cannot() -> None:
    found = assign_heading(
        {
            "title": "Companies Act 2006",
            "source_url": "https://www.legislation.gov.uk/ukpga/2006/46/section/9",
        }
    )
    assert found.locator_map() == {"section": "9"}
    assert found.evidence == "source_url"
    assert found.site == "legislation.gov.uk"
    assert found.site_from == "source_url"
    assert found.instrument == "Companies Act 2006"
    assert "2006" not in found.locator_map().values()
    assert "46" not in found.locator_map().values()
    fragment = assign_heading(
        {"title": "Payment terms", "source_url": "https://example.test/loi#section-9"}
    )
    assert fragment.locator_map() == {"section": "9"}
    article = assign_heading(
        {"title": "Payment terms", "source_url": "https://example.test/article-12"}
    )
    assert article.locator_map() == {"article": "12", "section": "12"}
    site_only = assign_heading(
        {"title": "Payment terms", "source_url": "https://example.test/fr/loi"}
    )
    assert site_only.status == "unresolved"
    assert site_only.locators == ()
    assert site_only.site == "example.test"
    assert site_only.evidence == "site"
    banner = assign_heading(
        {
            "title": "Einrichtung der Gerichtsbehörden - § 1",
            "text": "Bundesrecht konsolidiert www.ris.bka.gv.at Seite 2 von 2",
        }
    )
    assert banner.locator_map() == {"section": "1"}
    assert banner.site == "ris.bka.gv.at"
    assert banner.site_from == "text"
    assert banner.instrument == "Einrichtung der Gerichtsbehörden"


def test_a_cross_reference_and_an_act_year_are_not_the_heading() -> None:
    cross = assign_heading(
        {
            "title": "Agency establishment",
            "text": (
                "The Agency is an independent Agency established pursuant to Article 142 "
                "of the constitution and shall report each year."
            ),
        }
    )
    assert cross.status == "unresolved"
    assert cross.locators == ()
    opening = assign_heading(
        {
            "title": "Wage payment",
            "text": "§ 4. The wage shall be paid each month.\nArticle 142 is unchanged.",
        }
    )
    assert opening.locator_map() == {"section": "4"}
    assert opening.evidence == "text_heading"
    year = assign_heading({"title": "Superannuation Act 1950"})
    assert year.status == "instrument_only"
    assert year.locators == ()
    assert year.instrument == "Superannuation Act 1950"
    caps = assign_heading(
        {"title": "TREATY ESTABLISHING THE EUROPEAN ATOMIC ENERGY COMMUNITY"}
    )
    assert caps.status == "instrument_only"
    ireland = assign_heading(
        {
            "title": "1 1. In this Act the expression the Principal Act means the earlier Act.",
            "statute": "ACT 2/1922",
        }
    )
    assert ireland.locator_map() == {"section": "1"}
    assert ireland.instrument == "ACT 2/1922"


def test_annexes_lettered_sections_and_treaty_titles_keep_their_heading() -> None:
    annex = assign_heading({"title": "Article Annexe"})
    assert annex.locator_map() == {"article": "Annexe", "section": "Annexe"}
    numbered = assign_heading({"title": "Article ANNEXE II"})
    assert numbered.locator_map()["article"] == "Annexe II"
    tail = assign_heading({"title": "Einrichtung der Gerichtsbehörden - Art. 11 § 2"})
    assert tail.locator_map() == {"article": "11", "section": "2"}
    assert tail.instrument == "Einrichtung der Gerichtsbehörden"
    assert tail.hierarchy_path == "Article 11 / Section 2"
    anlage = assign_heading(
        {"title": "Grundzüge für die Organisierung des Staatsbaudienstes - Anl. 1"}
    )
    assert anlage.locator_map() == {"section": "1"}
    assert anlage.instrument.startswith("Grundzüge")
    lettered = assign_heading(
        {
            "title": "15AB Use of extrinsic material in the interpretation of an Act",
            "statute": "Act 2/1901",
        }
    )
    assert lettered.locator_map() == {"section": "15AB"}
    assert lettered.instrument == "Act 2/1901"
    ordinal = assign_heading({"title": "1st Place in the list"})
    assert ordinal.locators == ()
    treaty = assign_heading(
        {
            "title": (
                "TREATY ESTABLISHING THE EUROPEAN ATOMIC ENERGY COMMUNITY, "
                "TITLE TWO - PROVISIONS FOR THE ENCOURAGEMENT OF PROGRESS"
            )
        }
    )
    assert treaty.locator_map()["title"] == "2"
    assert treaty.instrument.startswith("TREATY ESTABLISHING")
    spelled = assign_heading({"title": "Article Eight"})
    assert spelled.locator_map() == {"article": "8", "section": "8"}
    compound = assign_heading({"title": "Article Twenty Eight"})
    assert compound.locator_map()["article"] == "28"
    order = assign_heading(
        {"title": "The Appropriation (nr. 2) (Northern Ireland) Order 1973"}
    )
    assert order.status == "instrument_only"
    assert order.locators == ()
    assert "1973" not in order.locator_map().values()
    decimal = assign_heading({"title": "490.02905 Application for exemption order"})
    assert decimal.locator_map() == {"section": "490.02905"}
    decree = assign_heading(
        {
            "title": (
                "Beschluß der Provisorischen Nationalversammlung über die Aufhebung der Zensur"
            )
        }
    )
    assert decree.status == "instrument_only"
    assert decree.locators == ()


def test_an_empty_context_stays_unresolved() -> None:
    found = assign_heading({"title": "Payment terms", "text": _SHALL})
    assert found.status == "unresolved"
    assert found.evidence == "none"
    assert found.locators == ()
    assert found.site == ""
    assert found.instrument == ""


def test_admission_keeps_a_locator_the_splitter_already_set() -> None:
    decision = admit_source_law(
        {
            "id": "fr-1",
            "title": "Loi exemple",
            "text": _ACT,
            "source_url": "https://example.test/fr/loi",
            "language": "fr",
            "jurisdiction": "FR",
            "country": "France",
            "section_number": "99",
            "hierarchy_kind": "section",
            "metadata_json": "{}",
        },
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 2
    first = decision.records[0]["provenance"]
    assert first["article"] == "1"
    assert first.get("section") != "99"
    assert "heading_status" not in first
    assert "heading_site" not in first


def test_admission_fills_a_heading_from_the_source_row_and_the_url() -> None:
    danish = _located(
        _law(
            title="§ 4. Wages",
            section_number="4",
            hierarchy_kind="section",
            hierarchy_path="Section 4",
            source_type="retsinformation",
            instrument_title="Lov om løn",
            official_identifier="10000",
        )
    )
    assert danish["section"] == "4"
    assert danish.get("article") in {None, ""}
    assert danish["heading_evidence"] == "source_hierarchy"
    assert danish["heading_site"] == "retsinformation"
    assert danish["heading_instrument"] == "Lov om løn"
    assert danish.get("statute") != "10000"
    web = _located(
        _law(
            title="Companies Act 2006",
            source_url="https://www.legislation.gov.uk/ukpga/2006/46/section/9",
        )
    )
    assert web["section"] == "9"
    assert web["heading_site"] == "legislation.gov.uk"
    assert web["heading_instrument"] == "Companies Act 2006"
    instrument = _located(_law(title="Workers Compensation Act"))
    assert instrument["heading_status"] == "instrument_only"
    assert instrument.get("section") in {None, ""}
    assert instrument["heading_instrument"] == "Workers Compensation Act"
    unresolved = _located(_law(title="Payment terms", source_type="bulletin"))
    assert unresolved["heading_status"] == "unresolved"
    assert unresolved.get("section") in {None, ""}
    assert unresolved["heading_site"] == "bulletin"
    assert unresolved["heading_site_from"] == "source_type"


def test_a_parquet_fill_keeps_the_source_hierarchy_columns(tmp_path: Path) -> None:
    source = tmp_path / "laws.parquet"
    pq.write_table(
        pa.table(
            {
                "id": ["dk-4"],
                "title": ["Wage payment"],
                "text": [_SHALL],
                "language": ["da"],
                "jurisdiction": ["DK"],
                "source_url": [""],
                "section_number": ["4"],
                "hierarchy_kind": ["section"],
                "hierarchy_path": ["Section 4"],
                "instrument_title": ["Lov om løn"],
                "source_type": ["retsinformation"],
                "official_identifier": ["10000"],
            }
        ),
        source,
    )
    report = fill_country_parquet(
        source,
        tmp_path / "out",
        source_dataset="endomorphosis/ipfs_denmark_laws",
        source_revision=_SHA,
    )
    assert report["rows_read"] == 1
    assert report["atoms_written"] == 1
    assert report["atoms_with_locator"] == 1
    written = pq.read_table(tmp_path / "out" / "denmark" / "part-000000.parquet")
    provenance = json.loads(written.column("provenance")[0].as_py())
    assert provenance["section"] == "4"
    assert provenance["heading_evidence"] == "source_hierarchy"
    assert provenance["heading_site"] == "retsinformation"
    assert provenance["heading_instrument"] == "Lov om løn"
    assert provenance["jsonld"]["@type"] == "Legislation"
