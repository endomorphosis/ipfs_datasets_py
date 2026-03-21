from __future__ import annotations

import json
import subprocess

import pytest

from ipfs_datasets_py.processors.legal_scrapers import state_procedure_rules_scraper as procedure_module


class _DummyFetcher:
    def __init__(self) -> None:
        self.events = []
        self.cached = []

    async def _fetch_page_content_with_archival_fallback(self, url: str, timeout_seconds: int = 120):
        return b""

    def _record_fetch_event(self, provider: str, success: bool, error: str | None = None) -> None:
        self.events.append({"provider": provider, "success": success, "error": error})

    async def _store_page_bytes_in_ipfs_cache(self, url: str, payload: bytes, provider: str) -> None:
        self.cached.append({"url": url, "payload": payload, "provider": provider})


def test_extract_rhode_island_rule_links_discovers_rule_pages_and_pdfs() -> None:
    html = """
    <html><body>
      <a href="/Legal-Resources/Pages/Supreme-Court-Rules.aspx">Supreme Court Rules</a>
      <a href="/Legal-Resources/Documents/RulesOfEvidence.pdf">Rules of Evidence</a>
      <a href="/Forms/Small Claims Notice of Suit - Complaint (Attorney - No Instructions).pdf">Small Claims Notice of Suit - Complaint (Attorney - No Instructions)</a>
      <a href="/about">About</a>
    </body></html>
    """

    rows = procedure_module._extract_rhode_island_rule_links(
        html,
        "https://www.courts.ri.gov/Legal-Resources/Pages/court-rules.aspx",
    )

    assert rows == [
        {
            "label": "Supreme Court Rules",
            "url": "https://www.courts.ri.gov/Legal-Resources/Pages/Supreme-Court-Rules.aspx",
            "kind": "page",
        },
        {
            "label": "Rules of Evidence",
            "url": "https://www.courts.ri.gov/Legal-Resources/Documents/RulesOfEvidence.pdf",
            "kind": "pdf",
        },
    ]


def test_extract_michigan_rules_from_html_parses_rule_blocks() -> None:
    html = """
    <html><body>
      <h1>Court Rules Chapter 2</h1>
      <p>MICHIGAN COURT RULES OF 1985</p>
      <p>Chapter 2. Civil Procedure</p>
      <p>Chapter Updated with MSC Order(s) Effective on October 1, 2025</p>
      <p>Rule 2.001 Applicability</p>
      <p>The rules in this chapter govern procedure in all civil proceedings.</p>
      <p>Rule 2.002 Waiver of Fees for Indigent Persons</p>
      <p>A request to waive fees must accompany the documents the individual is filing.</p>
    </body></html>
    """

    statutes = procedure_module._extract_michigan_rules_from_html(
        html,
        chapter_url="https://www.courts.michigan.gov/example/ch2.htm",
        code_name="Michigan Court Rules",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
    )

    assert len(statutes) == 2
    assert statutes[0].section_number == "2.001"
    assert statutes[0].section_name == "Applicability"
    assert statutes[0].official_cite == "MCR 2.001"
    assert statutes[0].structured_data["effective_date"] == "October 1, 2025"
    assert "civil proceedings" in statutes[0].full_text


def test_extract_california_rule_links_and_rule_page() -> None:
    title_html = """
    <html><body><main>
      <p>California Rules of Court</p>
      <p>2026</p>
      <p>Title Three. Civil Rules</p>
      <p>Current as of July 1, 2025</p>
      <a href="/cms/rules/index/three/rule3_10">Rule 3.10. Application</a>
      <a href="/cms/rules/index/three/rule3_20">Rule 3.20. Preemption of local rules</a>
    </main></body></html>
    """

    links, current_as_of = procedure_module._extract_california_rule_links(
        title_html,
        title_url="https://courts.ca.gov/cms/rules/index/three",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
    )

    assert current_as_of == "July 1, 2025"
    assert links == [
        {
            "label": "Rule 3.10. Application",
            "url": "https://courts.ca.gov/cms/rules/index/three/rule3_10",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
        },
        {
            "label": "Rule 3.20. Preemption of local rules",
            "url": "https://courts.ca.gov/cms/rules/index/three/rule3_20",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
        },
    ]

    rule_html = """
    <html><body><main>
      <p>Previous rule</p>
      <p>Back to Table of Contents</p>
      <p>California Rules of Court</p>
      <p>2026</p>
      <p>Rule 3.10. Application</p>
      <p>These rules apply to civil cases in California courts.</p>
      <p>Rule 3.10 adopted effective January 1, 2007.</p>
    </main></body></html>
    """

    statute = procedure_module._extract_california_rule_from_html(
        rule_html,
        rule_url="https://courts.ca.gov/cms/rules/index/three/rule3_10",
        code_name="California Rules of Court",
        title_name="Title Three. Civil Rules",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        current_as_of="July 1, 2025",
    )

    assert statute is not None
    assert statute.section_number == "3.10"
    assert statute.section_name == "Application"
    assert statute.official_cite == "Cal. Rules of Court, rule 3.10"
    assert statute.structured_data["current_as_of"] == "July 1, 2025"
    assert "civil cases" in statute.full_text


def test_extract_ohio_rules_from_text_parses_rule_blocks() -> None:
    text = """
    OHIO RULES OF CIVIL PROCEDURE
    TITLE I. SCOPE OF RULES
    RULE 1. Scope of rules: applicability; construction; exceptions.
    These rules prescribe the procedure to be followed in all courts of this state in the exercise of civil jurisdiction.
    Effective Date: July 1, 1970
    RULE 2. One form of action.
    There shall be one form of action to be known as a civil action.
    Effective Date: July 1, 1970
    """

    statutes = procedure_module._extract_ohio_rules_from_text(
        text,
        source_url="https://www.supremecourt.ohio.gov/docs/LegalResources/Rules/civil/CivilProcedure.pdf",
        title_name="Ohio Rules of Civil Procedure",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        effective_date="July 1, 2025",
    )

    assert len(statutes) == 2
    assert statutes[0].section_number == "1"
    assert statutes[0].section_name.startswith("Scope of rules: applicability; construction; exceptions")
    assert statutes[0].official_cite == "Ohio Rules of Civil Procedure Rule 1"
    assert statutes[0].structured_data["effective_date"] == "July 1, 2025"
    assert "procedure to be followed" in statutes[0].full_text


def test_extract_arizona_rules_from_text_parses_rule_blocks() -> None:
    text = """
    Rules of Civil Procedure for the Superior Courts of Arizona
    Table of Contents
    Rule 1. Scope and Purpose
    Rule 2. One Form of Action
    Prefatory Comment to the 2017 Amendments
    I. SCOPE OF RULES-ONE FORM OF ACTION
    Rule 1. Scope and Purpose. These rules govern the procedure in all civil actions and proceedings in the superior court of Arizona.
    Rule 2. One Form of Action. There is one form of action-the civil action.
    """

    statutes = procedure_module._extract_arizona_rules_from_text(
        text,
        source_url="https://www.azcourts.gov/example/arcp.pdf",
        title_name="Arizona Rules of Civil Procedure",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        effective_date="2017 amendments restyled text reflected in official PDF",
        start_marker="Rule 1. Scope and Purpose",
    )

    assert len(statutes) >= 1
    assert statutes[0].section_number == "1"
    assert statutes[0].section_name.startswith("Scope and Purpose")
    assert statutes[0].official_cite == "Arizona Rules of Civil Procedure Rule 1"
    assert "civil actions and proceedings" in statutes[0].full_text


def test_extract_nebraska_rule_links_and_rule_page() -> None:
    article_html = """
    <html><body><article class="node">
      <div class="node__content">
        <a href="/supreme-court-rules/chapter-6-trial-courts/article-11/%C2%A7-6-1101-scope-and-purpose-rules">§ 6-1101. Scope and purpose of rules.</a>
        <a href="/supreme-court-rules/chapter-6-trial-courts/article-11/%C2%A7-6-1105-serving-and-filing-pleadings-and-other-documents">§ 6-1105. Serving and filing pleadings and other documents.</a>
      </div>
    </article></body></html>
    """

    links = procedure_module._extract_nebraska_rule_links(
        article_html,
        page_url="https://nebraskajudicial.gov/supreme-court-rules/chapter-6-trial-courts/article-11",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="Neb. Ct. R. Pldg.",
    )

    assert links == [
        {
            "section_number": "6-1101",
            "section_name": "Scope and purpose of rules",
            "url": "https://nebraskajudicial.gov/supreme-court-rules/chapter-6-trial-courts/article-11/%C2%A7-6-1101-scope-and-purpose-rules",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "Neb. Ct. R. Pldg.",
        },
        {
            "section_number": "6-1105",
            "section_name": "Serving and filing pleadings and other documents",
            "url": "https://nebraskajudicial.gov/supreme-court-rules/chapter-6-trial-courts/article-11/%C2%A7-6-1105-serving-and-filing-pleadings-and-other-documents",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "Neb. Ct. R. Pldg.",
        },
    ]

    rule_html = """
    <html><body><article class="node">
      <div class="node__content">
        <div class="field field--name-body field__item">
          <p>(a) Scope. These Rules govern pleading in civil actions filed on or after January 1, 2003.</p>
          <p>(b) Purpose. These Rules should be construed and administered to secure the just determination of every action.</p>
          <p>§ 6-1101 amended December 18, 2024, effective January 1, 2025.</p>
        </div>
      </div>
    </article></body></html>
    """

    statute = procedure_module._extract_nebraska_rule_from_html(
        rule_html,
        rule_url="https://nebraskajudicial.gov/supreme-court-rules/chapter-6-trial-courts/article-11/%C2%A7-6-1101-scope-and-purpose-rules",
        title_name="Nebraska Court Rules of Pleading in Civil Cases",
        section_number="6-1101",
        section_name="Scope and purpose of rules",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="Neb. Ct. R. Pldg.",
    )

    assert statute is not None
    assert statute.section_number == "6-1101"
    assert statute.section_name == "Scope and purpose of rules"
    assert statute.official_cite == "Neb. Ct. R. Pldg. § 6-1101"
    assert statute.structured_data["effective_date"] == "January 1, 2025"
    assert "civil actions" in statute.full_text


def test_extract_maryland_links_and_rule_page() -> None:
    title_html = """
    <html><body>
      <a href="/mdc/Browse/Home/Maryland/MarylandCodeCourtRules?guid=chapter100">Chapter 100. Commencement of Action and Process</a>
      <a href="/mdc/Browse/Home/Maryland/MarylandCodeCourtRules?guid=chapter200">Chapter 200. Parties</a>
    </body></html>
    """

    chapters = procedure_module._extract_maryland_chapter_links(
        title_html,
        page_url="https://govt.westlaw.com/mdc/Browse/Home/Maryland/MarylandCodeCourtRules?guid=title2",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
    )

    assert chapters == [
        {
            "chapter_number": "100",
            "chapter_name": "Commencement of Action and Process",
            "url": "https://govt.westlaw.com/mdc/Browse/Home/Maryland/MarylandCodeCourtRules?guid=chapter100",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
        },
        {
            "chapter_number": "200",
            "chapter_name": "Parties",
            "url": "https://govt.westlaw.com/mdc/Browse/Home/Maryland/MarylandCodeCourtRules?guid=chapter200",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
        },
    ]

    chapter_html = """
    <html><body>
      <a href="/mdc/Document/rule2101?viewType=FullText">Rule 2–101. Commencement of Action</a>
      <a href="/mdc/Document/rule2111?viewType=FullText">Rule 2–111. Process—Requirements Preliminary to Summons</a>
    </body></html>
    """

    rules = procedure_module._extract_maryland_rule_links(
        chapter_html,
        page_url="https://govt.westlaw.com/mdc/Browse/Home/Maryland/MarylandCodeCourtRules?guid=chapter100",
        title_name="Title 2. Civil Procedure--Circuit Court",
        chapter_name="Commencement of Action and Process",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
    )

    assert rules == [
        {
            "section_number": "2-101",
            "section_name": "Commencement of Action",
            "url": "https://govt.westlaw.com/mdc/Document/rule2101?viewType=FullText",
            "title_name": "Title 2. Civil Procedure--Circuit Court",
            "chapter_name": "Commencement of Action and Process",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
        },
        {
            "section_number": "2-111",
            "section_name": "Process-Requirements Preliminary to Summons",
            "url": "https://govt.westlaw.com/mdc/Document/rule2111?viewType=FullText",
            "title_name": "Title 2. Civil Procedure--Circuit Court",
            "chapter_name": "Commencement of Action and Process",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
        },
    ]

    rule_html = """
    <html><body>
      <div id="co_document">
        <p>West's Annotated Code of Maryland</p>
        <p>Maryland Rules</p>
        <p>Title 2. Civil Procedure--Circuit Court</p>
        <p>Chapter 100. Commencement of Action and Process</p>
        <p>MD Rules, Rule 2-101</p>
        <p>RULE 2-101. COMMENCEMENT OF ACTION</p>
        <p>Currentness</p>
        <p>(a) Generally. A civil action is commenced by filing a complaint with a court.</p>
        <p>Credits [Adopted April 6, 1984, eff. July 1, 1984.]</p>
        <p>Current with amendments received through February 1, 2026.</p>
        <p>End of Document</p>
      </div>
    </body></html>
    """

    statute = procedure_module._extract_maryland_rule_from_html(
        rule_html,
        rule_url="https://govt.westlaw.com/mdc/Document/rule2101?viewType=FullText",
        title_name="Title 2. Civil Procedure--Circuit Court",
        chapter_name="Commencement of Action and Process",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
    )

    assert statute is not None
    assert statute.section_number == "2-101"
    assert statute.section_name == "COMMENCEMENT OF ACTION"
    assert statute.official_cite == "Md. Rule 2-101"
    assert statute.structured_data["current_as_of"] == "February 1, 2026"
    assert "civil action is commenced" in statute.full_text


def test_extract_south_carolina_links_and_rule_page() -> None:
    list_html = """
    <html><body>
      <a href="/resources/judicial-community/court-rules/civil/rule-1/">1 SCOPE OF RULES</a>
      <a href="/resources/judicial-community/court-rules/civil/rule-4-1/">4.1 SERVICE OF PROCESS IN FOREIGN COUNTRIES</a>
      <a href="/resources/judicial-community/court-rules/criminal/rule-5/">5 DISCLOSURE IN CRIMINAL CASES</a>
    </body></html>
    """

    links = procedure_module._extract_south_carolina_rule_links(
        list_html,
        page_url="https://www.sccourts.org/resources/judicial-community/court-rules/civil/",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="SCRCP",
    )

    assert links == [
        {
            "section_number": "1",
            "section_name": "SCOPE OF RULES",
            "url": "https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-1/",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "SCRCP",
        },
        {
            "section_number": "4.1",
            "section_name": "SERVICE OF PROCESS IN FOREIGN COUNTRIES",
            "url": "https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-4-1/",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "SCRCP",
        },
    ]

    rule_html = """
    <html><body>
      <main id="main-content">
        <section class="content-section pt-5 pb-5">
          <div class="container">
            <div class="row">
              <a href="/resources/judicial-community/court-rules/civil/">Back To Court Rules</a>
              <a href="/resources/judicial-community/court-rules/civil/rule-2/">Next</a>
            </div>
            <p align="center"><strong>RULE 1<br />SCOPE OF RULES</strong></p>
            <p>These rules govern the procedure in all South Carolina courts in all suits of a civil nature.</p>
          </div>
        </section>
      </main>
    </body></html>
    """

    statute = procedure_module._extract_south_carolina_rule_from_html(
        rule_html,
        rule_url="https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-1/",
        title_name="South Carolina Rules of Civil Procedure",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="SCRCP",
    )

    assert statute is not None
    assert statute.section_number == "1"
    assert statute.section_name == "SCOPE OF RULES"
    assert statute.official_cite == "SCRCP Rule 1"
    assert "South Carolina courts" in statute.full_text


def test_extract_alaska_rules_from_text_parses_rule_blocks() -> None:
    text = """
    ALASKA RULES OF COURT
    RULES OF CIVIL PROCEDURE
    Table of Contents
    PART I. SCOPE OF RULES-CONSTRUCTION-ONE FORM OF ACTION
    Rule
    1 Scope of Rules-Construction.
    2 One Form of Action.

    Rule 1 Scope of Rules-Construction.
    These rules govern the procedure in the superior court in all suits of a civil nature.
    Rule 2 One Form of Action.
    There shall be one form of action to be known as \"civil action.\"
    """

    statutes = procedure_module._extract_alaska_rules_from_text(
        text,
        source_url="https://courts.alaska.gov/rules/docs/civ.pdf",
        title_name="Alaska Rules of Civil Procedure",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="Alaska R. Civ. P.",
        start_marker="Rule\n1 Scope of Rules",
    )

    assert len(statutes) >= 2
    assert statutes[0].section_number == "1"
    assert statutes[0].section_name.startswith("Scope of Rules")
    assert statutes[0].official_cite == "Alaska R. Civ. P. 1"
    assert "superior court" in statutes[0].full_text


def test_extract_hawaii_rules_from_html() -> None:
    html = """
    <html><body>
      <p>HAWAI‘I RULES OF CIVIL PROCEDURE</p>
      <p>Table of Contents</p>
      <p>Rule 1.</p>
      <p>SCOPE OF RULES; INTERPRETATION AND ENFORCEMENT;</p>
      <p>Rule 2.</p>
      <p>ONE FORM OF ACTION.</p>
      <p>I. SCOPE OF RULES -- ONE FORM OF ACTION</p>
      <p>Rule 1.</p>
      <p>SCOPE OF RULES; INTERPRETATION AND ENFORCEMENT;</p>
      <p>EFFECT OF ELECTRONIC FILING.</p>
      <p>(a)</p>
      <p>Scope of rules.</p>
      <p>These Rules govern the procedure in the circuit courts of the State in all suits of a civil nature.</p>
      <p>Rule 1.1.</p>
      <p>REGISTRATION REQUIRED.</p>
      <p>Each attorney shall register as a Judiciary Electronic Filing and Service System user.</p>
    </body></html>
    """

    statutes = procedure_module._extract_hawaii_rules_from_html(
        html,
        source_url="https://www.courts.state.hi.us/wp-content/uploads/2024/09/hrcp_ada.htm",
        title_name="Hawai‘i Rules of Civil Procedure",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="HRCP Rule",
        effective_date="January 1, 2026",
    )

    assert len(statutes) == 2
    assert statutes[0].section_number == "1"
    assert statutes[0].section_name == "SCOPE OF RULES; INTERPRETATION AND ENFORCEMENT; EFFECT OF ELECTRONIC FILING"
    assert statutes[0].official_cite == "HRCP Rule 1"
    assert statutes[0].structured_data["effective_date"] == "January 1, 2026"
    assert "circuit courts of the State" in statutes[0].full_text


def test_extract_washington_rule_links_and_rule_text() -> None:
    list_html = """
    <html><body>
      <table>
        <tr><td nowrap valign="top">1</td><td valign="top"><a href="../court_rules/pdf/CR/SUP_CR_01_00_00.pdf">Scope of Rules</a></td></tr>
        <tr><td nowrap valign="top">4.1</td><td valign="top"><a href="../court_rules/pdf/CR/SUP_CR_04_01_00.pdf">Process--Domestic Relations Actions</a></td></tr>
        <tr><td nowrap valign="top">3.1 Stds</td><td valign="top"><a href="../court_rules/pdf/CrR/SUP_CrR_03_01_Standards.pdf">Standards for Indigent Defense</a></td></tr>
      </table>
    </body></html>
    """

    links = procedure_module._extract_washington_rule_links(
        list_html,
        page_url="https://www.courts.wa.gov/court_rules/?fa=court_rules.list&group=sup&set=CR",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="CR",
    )

    assert links[:2] == [
        {
            "section_number": "1",
            "section_name": "Scope of Rules",
            "url": "https://www.courts.wa.gov/court_rules/pdf/CR/SUP_CR_01_00_00.pdf",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "CR",
        },
        {
            "section_number": "4.1",
            "section_name": "Process--Domestic Relations Actions",
            "url": "https://www.courts.wa.gov/court_rules/pdf/CR/SUP_CR_04_01_00.pdf",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "CR",
        },
    ]

    statute = procedure_module._extract_washington_rule_from_text(
        "CR 1 SCOPE OF RULES These rules govern the procedure in the superior court in all suits of a civil nature. [Adopted effective July 1, 1967; Amended effective July 9, 2024.]",
        source_url="https://www.courts.wa.gov/court_rules/pdf/CR/SUP_CR_01_00_00.pdf",
        title_name="Washington Superior Court Civil Rules",
        section_number="1",
        section_name="Scope of Rules",
        official_cite_prefix="CR",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
    )

    assert statute is not None
    assert statute.section_number == "1"
    assert statute.section_name == "Scope of Rules"
    assert statute.official_cite == "CR 1"
    assert statute.structured_data["effective_date"] == "July 9, 2024"
    assert "These rules govern the procedure" in statute.full_text


def test_extract_new_hampshire_rules_from_online_book_html() -> None:
    html = """
    <html><body>
      <div class="online__book__page" id="page-id-4776">
        <div class="online__book__page__content">
          <p>PREAMBLE</p>
          <p>These rules take effect on January 1, 2024 and apply to all criminal actions filed on or after that date.</p>
        </div>
      </div>
      <div class="online__book__page online__book__section-486" id="page-id-4781">
        <div class="online__book__page__header">
          <h4>Rule 1. Scope and Interpretation</h4>
        </div>
        <div class="online__book__page__content">
          <p>(a) Scope. These rules govern the procedure in circuit court-district division and superior courts.</p>
          <p>Comment. These rules apply to criminal proceedings.</p>
        </div>
      </div>
      <div class="online__book__page online__book__section-486" id="page-id-4786">
        <div class="online__book__page__header">
          <h4>Rule 2. Adoption and Effective Date; Applicability</h4>
        </div>
        <div class="online__book__page__content">
          <p>(a) Adoption. The Supreme Court adopts these rules.</p>
          <p>(b) Effective Date. These rules govern all proceedings filed on or after January 1, 2024.</p>
        </div>
      </div>
    </body></html>
    """

    statutes = procedure_module._extract_new_hampshire_rules_from_online_book_html(
        html,
        source_url="https://www.courts.nh.gov/new-hampshire-rules-criminal-procedure",
        title_name="New Hampshire Rules of Criminal Procedure",
        procedure_family="criminal_procedure",
        legal_area="criminal_procedure",
        official_cite_prefix="N.H. R. Crim. P.",
    )

    assert len(statutes) == 2
    assert statutes[0].section_number == "1"
    assert statutes[0].section_name == "Scope and Interpretation"
    assert statutes[0].official_cite == "N.H. R. Crim. P. 1"
    assert statutes[0].structured_data["effective_date"] == "January 1, 2024"
    assert statutes[0].source_url.endswith("#page-id-4781")
    assert "criminal proceedings" in statutes[0].full_text


def test_extract_nevada_rules_from_html() -> None:
    html = """
    <html><body>
      <p>ADOPTED</p>
      <p>Effective January 1, 1953</p>
      <p class="SectBody"><a name="NRCPRule1"></a>Rule 1. Scope and Purpose</p>
      <p class="SectBody">These rules govern the procedure in all civil actions and proceedings in the district courts.</p>
      <p class="SourceNote">[Amended; effective March 1, 2019.]</p>
      <p class="SectBody"><a name="NRCPRule2"></a>Rule 2. One Form of Action</p>
      <p class="SectBody">There is one form of action-the civil action.</p>
    </body></html>
    """

    statutes = procedure_module._extract_nevada_rules_from_html(
        html,
        source_url="https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/NRCP.html",
        title_name="Nevada Rules of Civil Procedure",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="NRCP",
    )

    assert len(statutes) == 2
    assert statutes[0].section_number == "1"
    assert statutes[0].section_name == "Scope and Purpose"
    assert statutes[0].official_cite == "NRCP 1"
    assert statutes[0].structured_data["effective_date"] == "March 1, 2019"
    assert statutes[0].source_url.endswith("#NRCPRule1")
    assert "civil actions" in statutes[0].full_text


def test_extract_connecticut_rules_from_page_texts() -> None:
    page_texts = [
        (1, "OFFICIAL 2026 CONNECTICUT PRACTICE BOOK"),
        (
            221,
            """
            SUPERIOR COURT—PROCEDURE IN CIVIL MATTERS Sec. 11-1
            CHAPTER 11
            MOTIONS, REQUESTS, ORDERS OF NOTICE AND SHORT CALENDAR
            Sec. 11-1. Form of Motion and Request
            (a) Every motion, request, application or objection directed to pleading or procedure shall be in writing.
            Sec. 11-2. Definition of “Motion” and “Request”
            A motion is any application to the court for an order.
            Sec. 11-5. Subsequent Orders of Notice; Continuance Motions made to the court for a second or subsequent order of notice shall be filed with the clerk.
            """,
        ),
        (
            389,
            """
            SUPERIOR COURT—PROCEDURE IN CRIMINAL MATTERS Sec. 36-1
            CHAPTER 36
            PROCEDURE PRIOR TO APPEARANCE
            Sec. 36-1. Arrest by Warrant; Issuance
            Upon the submission of an application for an arrest warrant by a prosecuting authority, a judicial authority may issue a warrant.
            Sec. 36-2. —Affidavit in Support of Application, Filing, Dis-
            closure
            The affidavit shall be filed with the clerk and shall be subject to disclosure.
            """,
        ),
    ]

    statutes = procedure_module._extract_connecticut_rules_from_page_texts(
        page_texts,
        source_url="https://jud.ct.gov/Publications/PracticeBook/PB.pdf",
    )

    assert len(statutes) == 5
    assert statutes[0].section_number == "11-1"
    assert statutes[0].section_name == "Form of Motion and Request"
    assert statutes[0].official_cite == "Conn. Practice Book § 11-1"
    assert statutes[0].structured_data["edition_year"] == "2026"
    assert statutes[0].structured_data["page_start"] == 221
    assert statutes[0].source_url.endswith("#page=221")
    assert statutes[2].section_number == "11-5"
    assert statutes[2].section_name == "Subsequent Orders of Notice; Continuance"
    assert "second or subsequent order of notice" in statutes[2].full_text
    assert statutes[3].section_number == "36-1"
    assert statutes[3].section_name == "Arrest by Warrant; Issuance"
    assert statutes[3].structured_data["procedure_family"] == "criminal_procedure"
    assert statutes[4].section_name == "—Affidavit in Support of Application, Filing, Disclosure"


def test_extract_idaho_rule_links_and_rule_page() -> None:
    list_html = """
    <html><body>
      <div class="field field-name-body">
        <div class="field-item" property="content:encoded">
          <h2>Idaho Criminal Rules (I.C.R.)</h2>
          <p>Rule 1. <a href="icr1">Scope - Courts - Exceptions</a></p>
          <p>Rule 2. <a href="icr2">Purpose and Construction; Title; District Court Rules</a></p>
        </div>
      </div>
    </body></html>
    """

    links = procedure_module._extract_idaho_rule_links(
        list_html,
        page_url="https://isc.idaho.gov/icr",
        procedure_family="criminal_procedure",
        legal_area="criminal_procedure",
        official_cite_prefix="I.C.R.",
    )

    assert links == [
        {
            "section_number": "1",
            "section_name": "Scope - Courts - Exceptions",
            "url": "https://isc.idaho.gov/icr1",
            "procedure_family": "criminal_procedure",
            "legal_area": "criminal_procedure",
            "official_cite_prefix": "I.C.R.",
        },
        {
            "section_number": "2",
            "section_name": "Purpose and Construction; Title; District Court Rules",
            "url": "https://isc.idaho.gov/icr2",
            "procedure_family": "criminal_procedure",
            "legal_area": "criminal_procedure",
            "official_cite_prefix": "I.C.R.",
        },
    ]

    rule_html = """
    <html><body>
      <div class="field field-name-body">
        <div class="field-item" property="content:encoded">
          <p><strong>Idaho Rules of Civil Procedure Rule 1. Scope of Rules; District Court Rules.</strong></p>
          <p><strong>(a) Title</strong>. These rules may be known and cited as the Idaho Rules of Civil Procedure.</p>
          <p><strong>(b) Scope of Rules</strong>. These rules govern the procedure in civil actions.</p>
          <p style="font-style: italic;">(Adopted March 1, 2016, effective July 1, 2016; amended September 30, 2024, effective October 1, 2024.)</p>
        </div>
      </div>
    </body></html>
    """

    statute = procedure_module._extract_idaho_rule_from_html(
        rule_html,
        rule_url="https://isc.idaho.gov/ircp1-new",
        title_name="Idaho Rules of Civil Procedure",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
        official_cite_prefix="I.R.C.P.",
    )

    assert statute is not None
    assert statute.section_number == "1"
    assert statute.section_name == "Scope of Rules; District Court Rules"
    assert statute.official_cite == "I.R.C.P. 1"
    assert statute.structured_data["effective_date"] == "October 1, 2024"
    assert "civil actions" in statute.full_text


def test_extract_maine_civil_rule_links_and_criminal_pages() -> None:
    civil_html = """
    <html><body>
      <div id="maincontent2">
        <h1>Maine Rules of Civil Procedure Complete with Advisory Notes</h1>
        <p>Last reviewed and edited January 26, 2026 Includes amendments effective September 23, 2024</p>
        <blockquote>
          <p><a href="text/MRCivPPlus/RULE%201.pdf">Rule 1 - Scope of Rules</a></p>
          <p><a href="text/MRCivPPlus/RULE%202.pdf">Rule 2 - One Form of Action</a></p>
        </blockquote>
      </div>
    </body></html>
    """

    links, reviewed_date, amendments_effective = procedure_module._extract_maine_civil_rule_links(
        civil_html,
        index_url="https://www.courts.maine.gov/rules/rules-civil.html",
    )

    assert reviewed_date == "January 26, 2026"
    assert amendments_effective == "September 23, 2024"
    assert links == [
        {
            "section_number": "1",
            "section_name": "Scope of Rules",
            "url": "https://www.courts.maine.gov/rules/text/MRCivPPlus/RULE%201.pdf",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "Me. R. Civ. P.",
        },
        {
            "section_number": "2",
            "section_name": "One Form of Action",
            "url": "https://www.courts.maine.gov/rules/text/MRCivPPlus/RULE%202.pdf",
            "procedure_family": "civil_procedure",
            "legal_area": "civil_procedure",
            "official_cite_prefix": "Me. R. Civ. P.",
        },
    ]

    civil_statute = procedure_module._extract_maine_civil_rule_from_text(
        "MAINE RULES OF CIVIL PROCEDURE RULE 1. SCOPE OF RULES These rules govern the procedure in all suits of a civil nature. Advisory Committee's Notes...",
        source_url="https://www.courts.maine.gov/rules/text/MRCivPPlus/RULE%201.pdf",
        section_number="1",
        section_name="Scope of Rules",
        reviewed_date="January 26, 2026",
        amendments_effective="September 23, 2024",
    )

    assert civil_statute is not None
    assert civil_statute.official_cite == "Me. R. Civ. P. 1"
    assert civil_statute.structured_data["effective_date"] == "September 23, 2024"

    criminal_page_texts = [
        (1, "Last reviewed and edited April 16, 2025 Including amendments effective May 1, 2025"),
        (
            17,
            """
            MAINE RULES OF UNIFIED CRIMINAL PROCEDURE
            I. SCOPE, PURPOSE, AND CONSTRUCTION
            RULE 1. TITLE, SCOPE, AND APPLICATION OF RULES
            (a) Title. These Rules may be known and cited as the Maine Rules of Unified Criminal Procedure.
            (b) Scope; Application. These Rules govern criminal proceedings.
            """,
        ),
        (
            19,
            """
            RULE 2. PURPOSE AND CONSTRUCTION
            These Rules are intended to provide for the just determination of every proceeding.
            RULE 3. THE COMPLAINT
            (a) Nature and Contents. The complaint shall be a plain, concise, and definite written statement of the essential facts.
            """,
        ),
    ]

    criminal_statutes = procedure_module._extract_maine_criminal_rules_from_page_texts(
        criminal_page_texts,
        source_url="https://www.courts.maine.gov/rules/text/mru_crim_p_only_2025-05-01.pdf",
    )

    assert len(criminal_statutes) == 3
    assert criminal_statutes[0].section_number == "1"
    assert criminal_statutes[0].section_name == "TITLE, SCOPE, AND APPLICATION OF RULES"
    assert criminal_statutes[0].structured_data["effective_date"] == "May 1, 2025"
    assert criminal_statutes[2].official_cite == "Me. R. U. Crim. P. 3"


@pytest.mark.anyio
async def test_fetch_html_with_direct_fallback_uses_curl_when_requests_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher = _DummyFetcher()

    def _fake_requests_get(*_args, **_kwargs):
        raise RuntimeError("blocked")

    def _fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"<html><body><main>usable html</main></body></html>",
            stderr=b"",
        )

    monkeypatch.setattr(procedure_module.requests, "get", _fake_requests_get)
    monkeypatch.setattr(procedure_module, "_fetch_url_via_curl", lambda *args, **kwargs: (_fake_run().stdout, None))

    html = await procedure_module._fetch_html_with_direct_fallback(
        fetcher,
        "https://example.com/rules",
        validator=lambda value: "usable html" in value,
    )

    assert "usable html" in html
    assert fetcher.events[-1]["provider"] == "curl"
    assert fetcher.events[-1]["success"] is True
    assert fetcher.cached[-1]["provider"] == "curl"


@pytest.mark.anyio
async def test_fetch_json_with_direct_fallback_uses_curl_when_requests_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher = _DummyFetcher()

    def _fake_requests_get(*_args, **_kwargs):
        raise RuntimeError("blocked")

    payload = json.dumps([{"key": "26666", "title": "3:1-1-Scope"}]).encode("utf-8")
    monkeypatch.setattr(procedure_module.requests, "get", _fake_requests_get)
    monkeypatch.setattr(procedure_module, "_fetch_url_via_curl", lambda *args, **kwargs: (payload, None))

    parsed = await procedure_module._fetch_json_with_direct_fallback(
        fetcher,
        "https://example.com/api",
    )

    assert parsed == [{"key": "26666", "title": "3:1-1-Scope"}]
    assert fetcher.events[-1]["provider"] == "curl"
    assert fetcher.events[-1]["success"] is True
    assert fetcher.cached[-1]["provider"] == "curl"


def test_extract_new_jersey_rule_from_description() -> None:
    statute = procedure_module._extract_new_jersey_rule_from_description(
        """
        <div class="field__item">
          <p>Unless otherwise stated, the rules in Part I are applicable to the Supreme Court and the Superior Court.</p>
          <p><strong>Note:</strong> Amended November 22, 1978 to be effective December 7, 1978; amended December 20, 1983 to be effective December 31, 1983.</p>
        </div>
        """,
        section_number="1:1-1",
        section_name="Applicability; Scope",
        source_url="https://www.njcourts.gov/njcourts_rules_of_court/get-term?tid=24536#rule-1-1-1",
        title_name="New Jersey Court Rules Part I",
        procedure_family="civil_procedure",
        legal_area="civil_procedure",
    )

    assert statute is not None
    assert statute.section_number == "1:1-1"
    assert statute.section_name == "Applicability; Scope"
    assert statute.official_cite == "N.J. Ct. R. 1:1-1"
    assert statute.structured_data["effective_date"] == "December 31, 1983"
    assert "Supreme Court and the Superior Court" in statute.full_text


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_rhode_island_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "RI",
                    "state_name": "Rhode Island",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "RI": {
                        "attempted": 1,
                        "success": 1,
                        "success_ratio": 1.0,
                        "fallback_count": 0,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": None,
                    }
                }
            },
        }

    async def _fake_ri_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "RI",
                    "state_name": "Rhode Island",
                    "statute_id": "Rhode Island Court Rule Rules-Of-Civil-Procedure",
                    "section_number": "Rules-Of-Civil-Procedure",
                    "section_name": "Rules of Civil Procedure",
                    "full_text": "Rule 1. These rules govern civil actions in the Rhode Island superior court." + (" x" * 90),
                    "source_url": "https://www.courts.ri.gov/Courts/superiorcourt/Documents/SuperiorCourtRulesOfCivilProcedure.pdf",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "RI-rules-civil",
                            "name": "Rules of Civil Procedure",
                            "sectionNumber": "Rules-Of-Civil-Procedure",
                            "sectionName": "Rules of Civil Procedure",
                            "text": "Rule 1. These rules govern civil actions in the Rhode Island superior court." + (" x" * 90),
                            "sourceUrl": "https://www.courts.ri.gov/Courts/superiorcourt/Documents/SuperiorCourtRulesOfCivilProcedure.pdf",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "unified_scraper": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_rhode_island_court_rules_supplement",
        _fake_ri_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["RI"],
        write_jsonld=False,
    )

    assert result["status"] == "success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["RI"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["RI"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_oregon_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "OR",
                    "state_name": "Oregon",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "OR": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_or_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "OR",
                    "state_name": "Oregon",
                    "statute_id": "ORCP 1",
                    "section_number": "1",
                    "section_name": "Scope; Construction; Application; Rule; Citation",
                    "full_text": "ORCP 1 Scope; Construction; Application; Rule; Citation" + (" x" * 120),
                    "source_url": "https://www.oregonlegislature.gov/bills_laws/Pages/orcp.aspx#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "OR-orcp-1",
                            "name": "Scope; Construction; Application; Rule; Citation",
                            "sectionNumber": "1",
                            "sectionName": "Scope; Construction; Application; Rule; Citation",
                            "text": "ORCP 1 Scope; Construction; Application; Rule; Citation" + (" x" * 120),
                            "sourceUrl": "https://www.oregonlegislature.gov/bills_laws/Pages/orcp.aspx#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"direct": 1, "ipfs_page_cache": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_oregon_court_rules_supplement",
        _fake_or_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["OR"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["OR"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["OR"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_michigan_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "MI",
                    "state_name": "Michigan",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "MI": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_mi_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "MI",
                    "state_name": "Michigan",
                    "statute_id": "MCR 2.001",
                    "section_number": "2.001",
                    "section_name": "Applicability",
                    "full_text": "The rules in this chapter govern procedure in all civil proceedings." + (" x" * 120),
                    "source_url": "https://www.courts.michigan.gov/example/ch2.htm#rule-2.001",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "MI-mcr-2.001",
                            "name": "Applicability",
                            "sectionNumber": "2.001",
                            "sectionName": "Applicability",
                            "text": "The rules in this chapter govern procedure in all civil proceedings." + (" x" * 120),
                            "sourceUrl": "https://www.courts.michigan.gov/example/ch2.htm#rule-2.001",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "unified_scraper": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_michigan_court_rules_supplement",
        _fake_mi_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["MI"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["MI"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["MI"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_california_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "CA",
                    "state_name": "California",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "CA": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_ca_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "CA",
                    "state_name": "California",
                    "statute_id": "Cal. Rules of Court, rule 3.10",
                    "section_number": "3.10",
                    "section_name": "Application",
                    "full_text": "These rules apply to civil cases in California courts." + (" x" * 120),
                    "source_url": "https://courts.ca.gov/cms/rules/index/three/rule3_10",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "CA-rule-3.10",
                            "name": "Application",
                            "sectionNumber": "3.10",
                            "sectionName": "Application",
                            "text": "These rules apply to civil cases in California courts." + (" x" * 120),
                            "sourceUrl": "https://courts.ca.gov/cms/rules/index/three/rule3_10",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_california_court_rules_supplement",
        _fake_ca_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["CA"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["CA"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["CA"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_washington_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "WA",
                    "state_name": "Washington",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "WA": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_wa_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "WA",
                    "state_name": "Washington",
                    "statute_id": "CR 1",
                    "section_number": "1",
                    "section_name": "Scope of Rules",
                    "full_text": "CR 1 SCOPE OF RULES These rules govern the procedure in the superior court." + (" x" * 120),
                    "source_url": "https://www.courts.wa.gov/court_rules/pdf/CR/SUP_CR_01_00_00.pdf#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "WA-cr-1",
                            "name": "Scope of Rules",
                            "sectionNumber": "1",
                            "sectionName": "Scope of Rules",
                            "text": "CR 1 SCOPE OF RULES These rules govern the procedure in the superior court." + (" x" * 120),
                            "sourceUrl": "https://www.courts.wa.gov/court_rules/pdf/CR/SUP_CR_01_00_00.pdf#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_washington_court_rules_supplement",
        _fake_wa_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["WA"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["WA"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["WA"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_new_jersey_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "NJ",
                    "state_name": "New Jersey",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "NJ": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_nj_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "NJ",
                    "state_name": "New Jersey",
                    "statute_id": "N.J. Ct. R. 3:1-1",
                    "section_number": "3:1-1",
                    "section_name": "Scope",
                    "full_text": "Unless otherwise stated, the rules in Part III govern criminal proceedings." + (" x" * 120),
                    "source_url": "https://www.njcourts.gov/njcourts_rules_of_court/get-term?tid=26666#rule-3-1-1",
                    "procedure_family": "criminal_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "NJ-3-1-1",
                            "name": "Scope",
                            "sectionNumber": "3:1-1",
                            "sectionName": "Scope",
                            "text": "Unless otherwise stated, the rules in Part III govern criminal proceedings." + (" x" * 120),
                            "sourceUrl": "https://www.njcourts.gov/njcourts_rules_of_court/get-term?tid=26666#rule-3-1-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_new_jersey_court_rules_supplement",
        _fake_nj_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["NJ"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "criminal_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["NJ"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["NJ"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_new_hampshire_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "NH",
                    "state_name": "New Hampshire",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "NH": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_nh_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "NH",
                    "state_name": "New Hampshire",
                    "statute_id": "N.H. R. Crim. P. 1",
                    "section_number": "1",
                    "section_name": "Scope and Interpretation",
                    "full_text": "Rule 1. Scope and Interpretation. These rules govern criminal procedure in superior court." + (" x" * 120),
                    "source_url": "https://www.courts.nh.gov/new-hampshire-rules-criminal-procedure#page-id-4781",
                    "procedure_family": "criminal_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "NH-crim-rule-1",
                            "name": "Scope and Interpretation",
                            "sectionNumber": "1",
                            "sectionName": "Scope and Interpretation",
                            "text": "Rule 1. Scope and Interpretation. These rules govern criminal procedure in superior court." + (" x" * 120),
                            "sourceUrl": "https://www.courts.nh.gov/new-hampshire-rules-criminal-procedure#page-id-4781",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_new_hampshire_court_rules_supplement",
        _fake_nh_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["NH"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "criminal_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["NH"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["NH"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_nevada_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "NV",
                    "state_name": "Nevada",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "NV": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_nv_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "NV",
                    "state_name": "Nevada",
                    "statute_id": "NRCP 1",
                    "section_number": "1",
                    "section_name": "Scope and Purpose",
                    "full_text": "Rule 1. Scope and Purpose. These rules govern civil actions in the district courts." + (" x" * 120),
                    "source_url": "https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/NRCP.html#NRCPRule1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "NV-nrcp-1",
                            "name": "Scope and Purpose",
                            "sectionNumber": "1",
                            "sectionName": "Scope and Purpose",
                            "text": "Rule 1. Scope and Purpose. These rules govern civil actions in the district courts." + (" x" * 120),
                            "sourceUrl": "https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/NRCP.html#NRCPRule1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_nevada_court_rules_supplement",
        _fake_nv_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["NV"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["NV"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["NV"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_connecticut_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "CT",
                    "state_name": "Connecticut",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "CT": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_ct_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "CT",
                    "state_name": "Connecticut",
                    "statute_id": "Conn. Practice Book § 11-1",
                    "section_number": "11-1",
                    "section_name": "Form of Motion and Request",
                    "full_text": "Sec. 11-1. Form of Motion and Request\n(a) Every motion shall be in writing." + (" x" * 120),
                    "source_url": "https://jud.ct.gov/Publications/PracticeBook/PB.pdf#page=221",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "CT-pb-11-1",
                            "name": "Form of Motion and Request",
                            "sectionNumber": "11-1",
                            "sectionName": "Form of Motion and Request",
                            "text": "Sec. 11-1. Form of Motion and Request\n(a) Every motion shall be in writing." + (" x" * 120),
                            "sourceUrl": "https://jud.ct.gov/Publications/PracticeBook/PB.pdf#page=221",
                        }
                    },
                }
            ],
            {
                "attempted": 1,
                "success": 1,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 0,
                "cache_writes": 1,
                "providers": {"direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_connecticut_court_rules_supplement",
        _fake_ct_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["CT"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["CT"]["attempted"] == 2
    assert result["metadata"]["fetch_analytics_by_state"]["CT"]["cache_writes"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_idaho_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "ID",
                    "state_name": "Idaho",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "ID": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_id_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "ID",
                    "state_name": "Idaho",
                    "statute_id": "I.R.C.P. 1",
                    "section_number": "1",
                    "section_name": "Scope of Rules; District Court Rules",
                    "full_text": "Idaho Rules of Civil Procedure Rule 1. Scope of Rules; District Court Rules." + (" x" * 120),
                    "source_url": "https://isc.idaho.gov/ircp1-new#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "ID-ircp-1",
                            "name": "Scope of Rules; District Court Rules",
                            "sectionNumber": "1",
                            "sectionName": "Scope of Rules; District Court Rules",
                            "text": "Idaho Rules of Civil Procedure Rule 1. Scope of Rules; District Court Rules." + (" x" * 120),
                            "sourceUrl": "https://isc.idaho.gov/ircp1-new#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_idaho_court_rules_supplement",
        _fake_id_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["ID"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["ID"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["ID"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_maine_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "ME",
                    "state_name": "Maine",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "ME": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_me_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "ME",
                    "state_name": "Maine",
                    "statute_id": "Me. R. Civ. P. 1",
                    "section_number": "1",
                    "section_name": "Scope of Rules",
                    "full_text": "RULE 1. SCOPE OF RULES These rules govern the procedure in civil actions." + (" x" * 120),
                    "source_url": "https://www.courts.maine.gov/rules/text/MRCivPPlus/RULE%201.pdf#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "ME-mrcivp-1",
                            "name": "Scope of Rules",
                            "sectionNumber": "1",
                            "sectionName": "Scope of Rules",
                            "text": "RULE 1. SCOPE OF RULES These rules govern the procedure in civil actions." + (" x" * 120),
                            "sourceUrl": "https://www.courts.maine.gov/rules/text/MRCivPPlus/RULE%201.pdf#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_maine_court_rules_supplement",
        _fake_me_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["ME"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["ME"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["ME"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_nebraska_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "NE",
                    "state_name": "Nebraska",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "NE": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_ne_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "NE",
                    "state_name": "Nebraska",
                    "statute_id": "Neb. Ct. R. Pldg. § 6-1101",
                    "section_number": "6-1101",
                    "section_name": "Scope and purpose of rules",
                    "full_text": "§ 6-1101. Scope and purpose of rules. These Rules govern pleading in civil actions." + (" x" * 120),
                    "source_url": "https://nebraskajudicial.gov/example/%C2%A7-6-1101#section-6-1101",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "NE-6-1101",
                            "name": "Scope and purpose of rules",
                            "sectionNumber": "6-1101",
                            "sectionName": "Scope and purpose of rules",
                            "text": "§ 6-1101. Scope and purpose of rules. These Rules govern pleading in civil actions." + (" x" * 120),
                            "sourceUrl": "https://nebraskajudicial.gov/example/%C2%A7-6-1101#section-6-1101",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_nebraska_court_rules_supplement",
        _fake_ne_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["NE"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["NE"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["NE"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_maryland_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "MD",
                    "state_name": "Maryland",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "MD": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_md_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "MD",
                    "state_name": "Maryland",
                    "statute_id": "Md. Rule 2-101",
                    "section_number": "2-101",
                    "section_name": "COMMENCEMENT OF ACTION",
                    "full_text": "RULE 2-101. COMMENCEMENT OF ACTION A civil action is commenced by filing a complaint." + (" x" * 120),
                    "source_url": "https://govt.westlaw.com/mdc/Document/rule2101?viewType=FullText#rule-2-101",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "MD-2-101",
                            "name": "COMMENCEMENT OF ACTION",
                            "sectionNumber": "2-101",
                            "sectionName": "COMMENCEMENT OF ACTION",
                            "text": "RULE 2-101. COMMENCEMENT OF ACTION A civil action is commenced by filing a complaint." + (" x" * 120),
                            "sourceUrl": "https://govt.westlaw.com/mdc/Document/rule2101?viewType=FullText#rule-2-101",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_maryland_court_rules_supplement",
        _fake_md_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["MD"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["MD"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["MD"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_south_carolina_supplement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "SC",
                    "state_name": "South Carolina",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "SC": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_sc_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "SC",
                    "state_name": "South Carolina",
                    "statute_id": "SCRCP Rule 1",
                    "section_number": "1",
                    "section_name": "SCOPE OF RULES",
                    "full_text": "RULE 1 SCOPE OF RULES These rules govern the procedure in all South Carolina courts." + (" x" * 120),
                    "source_url": "https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-1/#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "SC-scrcp-1",
                            "name": "SCOPE OF RULES",
                            "sectionNumber": "1",
                            "sectionName": "SCOPE OF RULES",
                            "text": "RULE 1 SCOPE OF RULES These rules govern the procedure in all South Carolina courts." + (" x" * 120),
                            "sourceUrl": "https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-1/#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_south_carolina_court_rules_supplement",
        _fake_sc_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["SC"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["SC"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["SC"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_alaska_supplement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AK",
                    "state_name": "Alaska",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "AK": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_ak_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "AK",
                    "state_name": "Alaska",
                    "statute_id": "Alaska R. Civ. P. 1",
                    "section_number": "1",
                    "section_name": "Scope of Rules-Construction",
                    "full_text": "Rule 1 Scope of Rules-Construction. These rules govern the procedure in civil cases." + (" x" * 120),
                    "source_url": "https://courts.alaska.gov/rules/docs/civ.pdf#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "AK-civ-1",
                            "name": "Scope of Rules-Construction",
                            "sectionNumber": "1",
                            "sectionName": "Scope of Rules-Construction",
                            "text": "Rule 1 Scope of Rules-Construction. These rules govern the procedure in civil cases." + (" x" * 120),
                            "sourceUrl": "https://courts.alaska.gov/rules/docs/civ.pdf#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_alaska_court_rules_supplement",
        _fake_ak_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["AK"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["AK"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["AK"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_hawaii_supplement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "HI",
                    "state_name": "Hawaii",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "HI": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_hi_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "HI",
                    "state_name": "Hawaii",
                    "statute_id": "HRCP Rule 1",
                    "section_number": "1",
                    "section_name": "SCOPE OF RULES",
                    "full_text": "Rule 1. SCOPE OF RULES. These Rules govern the procedure in the circuit courts of the State." + (" x" * 120),
                    "source_url": "https://www.courts.state.hi.us/wp-content/uploads/2024/09/hrcp_ada.htm#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "HI-hrcp-1",
                            "name": "SCOPE OF RULES",
                            "sectionNumber": "1",
                            "sectionName": "SCOPE OF RULES",
                            "text": "Rule 1. SCOPE OF RULES. These Rules govern the procedure in the circuit courts of the State." + (" x" * 120),
                            "sourceUrl": "https://www.courts.state.hi.us/wp-content/uploads/2024/09/hrcp_ada.htm#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "direct": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_hawaii_court_rules_supplement",
        _fake_hi_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["HI"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["HI"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["HI"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_ohio_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "OH",
                    "state_name": "Ohio",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "OH": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_oh_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "OH",
                    "state_name": "Ohio",
                    "statute_id": "Ohio Rules of Civil Procedure Rule 1",
                    "section_number": "1",
                    "section_name": "Scope of rules: applicability; construction; exceptions",
                    "full_text": "RULE 1. Scope of rules: applicability; construction; exceptions " + ("x " * 140),
                    "source_url": "https://www.supremecourt.ohio.gov/docs/LegalResources/Rules/civil/CivilProcedure.pdf#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "OH-civ-rule-1",
                            "name": "Scope of rules: applicability; construction; exceptions",
                            "sectionNumber": "1",
                            "sectionName": "Scope of rules: applicability; construction; exceptions",
                            "text": "RULE 1. Scope of rules: applicability; construction; exceptions " + ("x " * 140),
                            "sourceUrl": "https://www.supremecourt.ohio.gov/docs/LegalResources/Rules/civil/CivilProcedure.pdf#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "unified_scraper": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_ohio_court_rules_supplement",
        _fake_oh_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["OH"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["OH"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["OH"]["cache_hits"] == 1


@pytest.mark.anyio
async def test_scrape_state_procedure_rules_adds_arizona_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**_kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "statutes": [],
                }
            ],
            "metadata": {
                "fetch_analytics_by_state": {
                    "AZ": {
                        "attempted": 1,
                        "success": 0,
                        "success_ratio": 0.0,
                        "fallback_count": 1,
                        "cache_hits": 0,
                        "cache_writes": 0,
                        "providers": {"unified_scraper": 1},
                        "last_error": "no procedure rules matched",
                    }
                }
            },
        }

    async def _fake_az_supplement(*, existing_source_urls=None, max_rules=None):
        assert existing_source_urls == set()
        assert max_rules is None
        return (
            [
                {
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "statute_id": "Arizona Rules of Civil Procedure Rule 1",
                    "section_number": "1",
                    "section_name": "Scope and Purpose",
                    "full_text": "Rule 1. Scope and Purpose. These rules govern the procedure in all civil actions and proceedings in the superior court of Arizona." + (" x" * 100),
                    "source_url": "https://www.azcourts.gov/example/arcp.pdf#rule-1",
                    "procedure_family": "civil_procedure",
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "AZ-arcp-rule-1",
                            "name": "Scope and Purpose",
                            "sectionNumber": "1",
                            "sectionName": "Scope and Purpose",
                            "text": "Rule 1. Scope and Purpose. These rules govern the procedure in all civil actions and proceedings in the superior court of Arizona." + (" x" * 100),
                            "sourceUrl": "https://www.azcourts.gov/example/arcp.pdf#rule-1",
                        }
                    },
                }
            ],
            {
                "attempted": 2,
                "success": 2,
                "success_ratio": 1.0,
                "fallback_count": 0,
                "cache_hits": 1,
                "cache_writes": 1,
                "providers": {"ipfs_page_cache": 1, "unified_scraper": 1},
                "last_error": None,
            },
        )

    monkeypatch.setattr(procedure_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        procedure_module,
        "_scrape_arizona_court_rules_supplement",
        _fake_az_supplement,
    )

    result = await procedure_module.scrape_state_procedure_rules(
        states=["AZ"],
        write_jsonld=False,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["rules_count"] == 1
    assert result["metadata"]["zero_rule_states"] is None
    assert result["data"][0]["rules_count"] == 1
    assert result["data"][0]["statutes"][0]["procedure_family"] == "civil_procedure"
    assert result["metadata"]["fetch_analytics_by_state"]["AZ"]["attempted"] == 3
    assert result["metadata"]["fetch_analytics_by_state"]["AZ"]["cache_hits"] == 1
