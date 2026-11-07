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


def test_a_provision_label_fills_the_section_and_a_street_does_not() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
        locators_from_provision_label,
    )

    assert locators_from_provision_label("Section 59", "59") == {"section": "59"}
    assert locators_from_provision_label("Section 44ZD", "") == {"section": "44ZD"}
    assert locators_from_provision_label(
        "Community Care and Health (Scotland) Act 2002",
        "",
        "1 1 Subject to subsection (2)(a) below, a local authority are not to charge.",
    ) == {"section": "1"}
    assert locators_from_provision_label(
        "Council of the Law Society of Scotland Act 2003",
        "",
        "1 After section 3 of the Solicitors (Scotland) Act 1980 insert the following.",
    ) == {"section": "1"}
    assert locators_from_provision_label("1.", "1") == {"section": "1"}
    assert locators_from_provision_label(
        "§ 1. I denne bekendtgørelse forstås ved:",
        "1",
    ) == {"section": "1"}
    assert locators_from_provision_label(
        "1 1. (1) The Fund mentioned in Article 61 of the Constitution shall be kept.",
        "ACT 2/1922",
    ) == {"section": "1"}
    assert locators_from_provision_label(
        "15AB Use of extrinsic material in the interpretation of an Act",
        "Act 2/1901",
    ) == {"section": "15AB"}
    assert locators_from_provision_label(
        "6.1 Reasons for declining to act on request",
        "",
    ) == {"section": "6.1"}
    assert locators_from_provision_label("§ 13 Satzung", "") == {"section": "13"}
    assert locators_from_provision_label("§ 1", "") == {"section": "1"}
    assert locators_from_provision_label(
        "§ 12 Wahrung von Betriebsgeheimnissen, Schutz personenbezogener Daten",
        "",
    ) == {"section": "12"}
    assert locators_from_provision_label("Art 3", "") == {"article": "3", "section": "3"}
    assert locators_from_provision_label(
        "126AKDG Inclusion of information in approved exporter database",
        "Act 6/1901",
    ) == {"section": "126AKDG"}
    assert locators_from_provision_label(
        "57-1 What this Division is about",
        "",
    ) == {"section": "57-1"}
    assert locators_from_provision_label("269-10 Trading", "") == {"section": "269-10"}
    assert locators_from_provision_label("Članak 8.", "") == {"article": "8", "section": "8"}
    assert locators_from_provision_label("s. 5.", "") == {"section": "5"}
    assert locators_from_provision_label("S. 15.", "") == {"section": "15"}
    assert locators_from_provision_label("5.19.1", "") == {"section": "5.19.1"}
    assert locators_from_provision_label(
        "1.3.2.",
        "",
        "1.3.2. A permanent establishment that is a constituent entity.",
    ) == {"section": "1.3.2"}
    assert locators_from_provision_label("2056.11.9", "", "2056.11.9 Amendment Rules") == {}
    assert locators_from_provision_label(
        "49.22.1 Vice-chair",
        "",
        "Vice-chair 49.22.1 (1) Convocation shall appoint a vice-chair.",
    ) == {"section": "49.22.1"}
    assert locators_from_provision_label(
        "Section 4.34A-CVL",
        "",
        "4.34A-CVL Where a liquidator is nominated by the company.",
    ) == {"section": "4.34A-CVL"}
    assert locators_from_provision_label("12-14 East Main Street", "") == {}
    assert locators_from_provision_label("s. 5. of the Act", "") == {}
    assert locators_from_provision_label("5.19.1 of the other regulation", "") == {}
    assert locators_from_provision_label("2010.1.1", "") == {}
    assert locators_from_provision_label("12.1.1 East Main Street", "") == {}
    assert locators_from_provision_label("C.01A.001", "") == {}
    assert locators_from_provision_label(
        "C.01A.001",
        "",
        "C.01A.001 In these Regulations, drug means a substance.",
    ) == {"section": "C.01A.001"}
    assert locators_from_provision_label(
        "B.01.002A",
        "",
        "B.01.002A The label of a food shall carry the following.",
    ) == {"section": "B.01.002A"}
    assert locators_from_provision_label(
        "C.01.004.01",
        "",
        "C.01.004.01 A manufacturer shall keep a record.",
    ) == {"section": "C.01.004.01"}
    assert locators_from_provision_label(
        "G.03.001 General information",
        "",
        "G.03.001 A practitioner shall record the following information.",
    ) == {"section": "G.03.001"}
    assert locators_from_provision_label(
        "C.01A.001 of the other regulation",
        "",
        "C.01A.001 of the other regulation is amended.",
    ) == {}
    assert locators_from_provision_label(
        "C.01A.001",
        "",
        "The schedule lists fees and does not recite that provision.",
    ) == {}
    assert locators_from_provision_label(
        "Artykuł 24. Article 24. Article i4.",
        "",
        "Artykuł 24. Article 24. Układające się Państwa będą się starały.",
    ) == {"article": "24", "section": "24"}
    assert locators_from_provision_label(
        "Artykuł 85.",
        "",
        "Artykuł 85. Każda ze Stron ponosi swoje własne koszty.",
    ) == {"article": "85", "section": "85"}
    assert locators_from_provision_label(
        "Artykuł 8. of the other law",
        "",
        "Artykuł 8. of the other law remains in force.",
    ) == {}
    assert locators_from_provision_label(
        "Artykuł 24.",
        "",
        "Artykuł 25. This article is a different provision.",
    ) == {}
    assert locators_from_provision_label("Članak 8. of the other law", "") == {}
    assert locators_from_provision_label(
        "Community Care and Health (Scotland) Act 2002",
        "",
        "216 East Main Street is the registered office.",
    ) == {}
    assert locators_from_provision_label(
        "The Police Reform Act 2002 is amended as follows",
        "2002",
        "1 After section 1 insert the following words.",
    ) == {}
    for title, statute in (
        ("216 East Main Street", "216"),
        ("The Police Reform Act 2002 is amended as follows", "2002"),
        ("216 East", ""),
        ("§ 4 of the other act", ""),
        ("Article 3 of the SEA", "3"),
        ("1. pantsuit", "1"),
        ("50 This is page 1 of 1 Page of the above Table.", "50"),
        ("IN THE HIGH COURT OF MALAWI", "9"),
        ("I.", "I"),
        ("The Police Reform Act 2002 is amended as follows", "2002"),
    ):
        assert locators_from_provision_label(title, statute) == {}


def test_a_latvian_punkts_title_is_the_article_when_the_body_opens_on_it() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
        locators_from_punkts_title,
    )

    body = "3. Regulators 2019.gada 16.augustā par tarifu projektu rīkoja uzklausīšanas sanāksmi."
    assert locators_from_punkts_title("3. punkts", body) == {"article": "3", "section": "3"}
    assert locators_from_punkts_title("3. punkts.", body) == {"article": "3", "section": "3"}
    assert locators_from_punkts_title("1. pants", "1. pants Šis likums nosaka tiesības.") == {}
    assert locators_from_punkts_title("1. pantsuit", "1. pantsuit is not a heading.") == {}
    for title in (
        "3. punktu",
        "3. punkta",
        "3. punkti",
        "3. punktā",
        "3. punktos",
        "3. punktiem",
        "3. punkts extra",
    ):
        assert locators_from_punkts_title(title, body) == {}, title
    assert locators_from_punkts_title("3. punkts", "") == {}
    assert locators_from_punkts_title("3. punkts", "4. Cits noteikums paliek spēkā.") == {}
    assert locators_from_punkts_title("3. punkts", "31. Šis ir cits numurs.") == {}
    assert locators_from_punkts_title(
        "1995. punkts",
        "1995. Gada noteikumi paliek spēkā visā valstī.",
    ) == {}


def test_a_code_provision_title_is_the_article_when_the_body_omits_it() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
        locators_from_code_title,
    )

    prose = (
        "Les fonctionnaires promus au grade de garde champêtre chef principal "
        "sont classés à l'échelon comportant un indice égal."
    )
    assert locators_from_code_title("Article 8-2", prose) == {
        "article": "8-2",
        "section": "8-2",
    }
    assert locators_from_code_title("Article 4 bis", prose) == {
        "article": "4 BIS",
        "section": "4 BIS",
    }
    assert locators_from_code_title("Article L111-2", prose) == {
        "article": "L111-2",
        "section": "L111-2",
    }
    assert locators_from_code_title("Article L. 111-1", prose) == {
        "article": "L.111-1",
        "section": "L.111-1",
    }
    assert locators_from_code_title("Article R*712-8", prose) == {
        "article": "R*712-8",
        "section": "R*712-8",
    }
    assert locators_from_code_title("Article R* 712-8", prose) == {
        "article": "R*712-8",
        "section": "R*712-8",
    }
    assert locators_from_code_title("Article *712-8", prose) == {}
    assert locators_from_code_title("Section 4.6A", prose) == {"section": "4.6A"}
    assert locators_from_code_title("Article 8-2", "1. Les matériaux utilisés restent soumis au contrôle.") == {
        "article": "8-2",
        "section": "8-2",
    }
    for title in (
        "Article Annexe",
        "Article Annexe I",
        "Article ANNEXE",
        "LEGIARTI000042976558",
        "Article 8-2 du code",
        "Article 216 East",
        "Arrêté du 25 janvier 1994 modifiant l'arrêté du 30 novembre 1988",
        "3. punkts",
    ):
        assert locators_from_code_title(title, prose) == {}, title
    assert locators_from_code_title("Article 8-2", "") == {}
    assert locators_from_code_title(
        "Article 8-2",
        "Article 9 Les dispositions du code restent applicables aux personnes concernées.",
    ) == {}
    assert locators_from_code_title("Article R*712-8 du code", prose) == {}


def test_a_marked_instrument_title_is_the_only_dash_pin() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
        locators_from_marked_title,
    )

    section, name = locators_from_marked_title("Einrichtung der Gerichtsbehörden - § 1")
    assert section == {"section": "1"}
    assert name == "Einrichtung der Gerichtsbehörden"
    article, name = locators_from_marked_title(
        "Politische und gerichtliche Organisierung des Erzherzogtumes Österreich ob der Enns - Art. 1"
    )
    assert article == {"article": "1", "section": "1"}
    assert name.startswith("Politische")
    both, _name = locators_from_marked_title("Einrichtung der Gerichtsbehörden - Art. 11 § 2")
    assert both == {"article": "11", "section": "2"}
    for title in (
        "216 East 42nd Street",
        "Article 3 of the SEA",
        "1. pantsuit",
        "The Police Reform Act 2002 is amended as follows",
    ):
        assert locators_from_marked_title(title) == ({}, "")


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


def test_code_numbers_ordinals_schedules_and_named_instruments() -> None:
    french = assign_heading({"title": "Article L22-10-38"})
    assert french.locator_map() == {"article": "L22-10-38", "section": "L22-10-38"}
    suffix = assign_heading({"title": "Article D910-1 B"})
    assert suffix.locator_map()["article"] == "D910-1 B"
    decimal = assign_heading({"title": "Section 4.6A"})
    assert decimal.locator_map() == {"section": "4.6A"}
    inserted = assign_heading({"title": "Section 36Z2"})
    assert inserted.locator_map() == {"section": "36Z2"}
    dotted = assign_heading({"title": "Section A.1"})
    assert dotted.locator_map() == {"section": "A.1"}
    volume = assign_heading({"title": "Section RVTD2.1"})
    assert volume.locator_map() == {"section": "RVTD2.1"}
    swiss = assign_heading({"title": "Art. T1-1"})
    assert swiss.locator_map()["article"] == "T1-1"
    letter = assign_heading({"title": "Section A"})
    assert letter.locator_map() == {"section": "A"}
    ordinal = assign_heading({"title": "Article Twenty second:"})
    assert ordinal.locator_map()["article"] == "22"
    hyphenated = assign_heading({"title": "Article Twenty-second"})
    assert hyphenated.locator_map()["article"] == "22"
    schedule = assign_heading({"title": "Schedule."})
    assert schedule.locator_map() == {"section": "Schedule"}
    roman = assign_heading({"title": "Schedule I."})
    assert roman.locator_map() == {"section": "Schedule I"}
    parenthetical = assign_heading({"title": "SCHEDULE (Section 4)"})
    assert parenthetical.locator_map() == {"section": "Schedule"}
    assert "4" not in parenthetical.locator_map().values()
    named = assign_heading({"title": "Schedule - Objects of Trust"})
    assert named.locator_map() == {"section": "Schedule"}
    assert named.instrument == "Objects of Trust"
    cross = assign_heading({"title": "Section C59 (1) or (2)."})
    assert cross.locators == ()
    prose = assign_heading({"title": "Schedule in which there is a law in force"})
    assert prose.locators == ()
    chapter = assign_heading({"title": "Cap 53-Births and Death Registration"})
    assert chapter.locator_map() == {"chapter": "53"}
    assert chapter.instrument.startswith("Births")
    scheme = assign_heading({"title": "The Premium Boar Scheme (Northern Ireland) 1974"})
    assert scheme.status == "instrument_only"
    assert scheme.locators == ()
    assert "1974" not in scheme.locator_map().values()
    warrant = assign_heading({"title": "The Inland Post Amendment (nr. 1) Warrant 1948"})
    assert warrant.status == "instrument_only"
    assert warrant.locators == ()
    measure = assign_heading({"title": "Vestures of Ministers Measure 1964"})
    assert measure.status == "instrument_only"
    assert measure.locators == ()
    licensing = assign_heading({"title": "94.-(1) A licensing scheme which has been confirmed or"})
    assert licensing.locators == ()
    assert licensing.status == "unresolved"
    long_act = (
        "An Act to continue the earlier Act until the year 1801 " + ("for the public peace " * 20)
    )
    assert len(long_act) > 300
    enacted = assign_heading({"title": long_act})
    assert enacted.status == "instrument_only"
    assert enacted.locators == ()
    assert "1801" not in enacted.locator_map().values()


def test_source_hierarchy_recovers_a_provision_the_atom_citation_does_not() -> None:
    order = "The Appropriation (nr. 2) (Northern Ireland) Order 1973"
    bare = assign_heading({"title": order, "citation": "1", "statute": "1"})
    assert bare.status == "instrument_only"
    assert bare.locators == ()
    recovered = assign_heading(
        {
            "title": order,
            "citation": "1",
            "statute": "1",
            "hierarchy_kind": "section",
            "section_number": "1",
            "article_number": "1",
            "hierarchy_path": "Part II > Section 1",
            "official_citation": "nisi 1973 1227, § 1",
            "instrument_title": order,
            "source_type": "legislation_gov_uk",
        }
    )
    assert recovered.status == "structural"
    assert recovered.evidence == "source_hierarchy"
    assert recovered.locator_map()["section"] == "1"
    assert recovered.locator_map()["part"] == "II"
    assert "1973" not in recovered.locator_map().values()
    assert "1227" not in recovered.locator_map().values()
    whole = assign_heading(
        {
            "title": "The Cattle Headage Payments (Amendment) Scheme (Northern Ireland) 1974",
            "hierarchy_kind": "law",
            "official_citation": "nisr 1974 53",
        }
    )
    assert whole.locators == ()
    year = assign_heading({"title": order, "hierarchy_kind": "section", "section_number": "1973"})
    assert year.locators == ()
    parenthetical = assign_heading(
        {"title": order, "hierarchy_path": "Article 11(5)"}
    )
    assert parenthetical.locator_map()["article"] == "11"
    assert parenthetical.locator_map()["section"] == "11"
    assert parenthetical.locator_map()["subsection"] == "5"
    assert parenthetical.hierarchy_path == "Article 11 / Subsection 5"


def test_widened_numbers_keep_the_base_and_a_real_tail() -> None:
    long_code = assign_heading(
        {"title": "103ZZGD Ultimate issue", "hierarchy_kind": "section", "section_number": "103ZZGD"}
    )
    assert long_code.locator_map() == {"section": "103ZZGD"}
    australia = assign_heading(
        {"title": "126AKDG Inclusion", "section_number": "126AKDG", "hierarchy_kind": "section"}
    )
    assert australia.locator_map() == {"section": "126AKDG"}
    vowels = assign_heading({"title": "153ZIKA Review", "section_number": "153ZIKA"})
    assert vowels.locator_map() == {"section": "153ZIKA"}
    glued = assign_heading({"section_number": "1ofthe", "hierarchy_kind": "section"})
    assert glued.locators == ()
    one_of = assign_heading({"title": "1of the Act"})
    assert one_of.locators == ()
    note = assign_heading({"title": "10.72D Conditions of exemption order"})
    assert note.locator_map() == {"section": "10.72D"}
    tail = assign_heading({"section_number": "338(2)", "hierarchy_kind": "section"})
    assert tail.locator_map() == {"section": "338", "subsection": "2"}
    assert tail.hierarchy_path == "Section 338 / Subsection 2"
    sibling = assign_heading(
        {
            "hierarchy_kind": "section",
            "section_number": "338",
            "article_number": "338(2)",
        }
    )
    assert sibling.locator_map() == {"section": "338", "subsection": "2"}
    arabic = assign_heading({"article_number": "المادة(35)", "hierarchy_kind": "article"})
    assert arabic.locator_map() == {"article": "35", "section": "35"}
    assert "subsection" not in arabic.locator_map()
    pinpoint = assign_heading({"section_number": "s. 5(4)", "hierarchy_kind": "section"})
    assert pinpoint.locator_map() == {"section": "5", "subsection": "4"}
    year = assign_heading({"section_number": "2010(1)", "hierarchy_kind": "section"})
    assert year.locators == ()
    doubled = assign_heading({"section_number": "102(a)(1)", "hierarchy_kind": "section"})
    assert doubled.locators == ()
    code = assign_heading({"section_number": "C.01A.001", "hierarchy_kind": "section"})
    assert code.locators == ()
    paragraph = assign_heading({"title": "para. 4"})
    assert paragraph.locators == ()
    delayed = assign_heading({"title": "Section 4 of the Act (1)"})
    assert delayed.locator_map() == {"section": "4"}
    assert "subsection" not in delayed.locator_map()
    marginal_tail = assign_heading({"title": "338(2) Powers of the court"})
    assert marginal_tail.locator_map() == {"section": "338", "subsection": "2"}
    empty_tail = assign_heading({"section_number": "(a)", "hierarchy_kind": "section"})
    assert empty_tail.locators == ()


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
    assert "heading_placement" not in danish
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
    assert instrument["heading_placement"] == "whole_instrument"
    unresolved = _located(_law(title="Payment terms", source_type="bulletin"))
    assert unresolved["heading_status"] == "unresolved"
    assert unresolved["heading_placement"] == "unresolved"
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
