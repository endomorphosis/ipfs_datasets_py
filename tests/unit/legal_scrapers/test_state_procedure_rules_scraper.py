from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers import state_procedure_rules_scraper as procedure_module


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
