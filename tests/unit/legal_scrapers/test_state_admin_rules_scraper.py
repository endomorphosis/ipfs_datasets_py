from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors import file_converter as file_converter_module
from ipfs_datasets_py.processors.legal_scrapers import legal_web_archive_search as legal_archive_module
from ipfs_datasets_py.processors.legal_scrapers import parallel_web_archiver as parallel_web_archiver_module
from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as scraper_module
from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
    _agentic_discover_admin_state_blocks,
    _allowed_discovery_hosts_for_state,
    _candidate_links_from_html,
    _candidate_montana_rule_urls_from_text,
    _candidate_utah_rule_urls_from_public_api,
    _is_admin_rule_statute,
    _is_relaxed_recovery_text,
    _is_substantive_rule_text,
    _is_substantive_admin_statute,
    _url_allowed_for_state,
    scrape_state_admin_rules,
)
from ipfs_datasets_py.processors.web_archiving import contracts as contracts_module
from ipfs_datasets_py.processors.web_archiving import unified_api as unified_api_module
from ipfs_datasets_py.processors.web_archiving import unified_web_scraper as unified_web_scraper_module


def test_rejects_rhode_island_statute_index_as_admin_rule() -> None:
    statute = {
        "code_name": "",
        "section_name": "TITLE 6 Commercial Law - General Regulatory Provisions",
        "source_url": "http://webserver.rilin.state.ri.us/Statutes/TITLE6/INDEX.HTM",
        "full_text": "TITLE 6 Commercial Law - General Regulatory Provisions",
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_curated_seeds_include_michigan_admin_rules_and_public_rhode_island_ricr() -> None:
    mi_urls = scraper_module._extract_seed_urls_for_state("MI", "Michigan")
    ri_urls = scraper_module._extract_seed_urls_for_state("RI", "Rhode Island")
    ut_urls = scraper_module._extract_seed_urls_for_state("UT", "Utah")

    assert "https://ars.apps.lara.state.mi.us/AdminCode/AdminCode" in mi_urls
    assert "https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306" in mi_urls
    assert "https://ars.apps.lara.state.mi.us/" not in mi_urls
    assert "https://ars.apps.lara.state.mi.us/Home" not in mi_urls
    assert any("rules.sos.ri.gov/regulations/part/" in url.lower() for url in ri_urls)
    assert "https://rules.sos.ri.gov/regulations/part/510-00-00-4" in ri_urls
    assert "https://rules.sos.ri.gov/regulations/part/510-00-00-20" in ri_urls
    assert all("rules.sos.ri.gov/organizations" not in url.lower() for url in ri_urls)
    assert "https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations" in ri_urls
    assert ut_urls[0] == "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules"


def test_curated_seeds_include_relocated_arizona_and_live_utah_search_entrypoints() -> None:
    az_urls = scraper_module._extract_seed_urls_for_state("AZ", "Arizona")
    ut_urls = scraper_module._extract_seed_urls_for_state("UT", "Utah")

    assert "https://azsos.gov/rules/arizona-administrative-code" in az_urls
    assert "https://apps.azsos.gov/public_services/CodeTOC.htm" in az_urls
    assert "https://apps.azsos.gov/public_services/Title_00.htm" not in az_urls

    assert "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules" in ut_urls
    assert "https://adminrules.utah.gov/public/home" not in ut_urls
    assert "https://adminrules.utah.gov/public/search" not in ut_urls


def test_rejects_indiana_archived_statute_pdfs_even_with_admin_like_code_name() -> None:
    statute = {
        "code_name": "Indiana Administrative Code",
        "section_name": "Indiana Code tit. 6, art. 1.1, ch. 15",
        "source_url": "http://web.archive.org/web/20170215063144/http://iga.in.gov/static-documents/0/0/5/2/005284ae/TITLE6_AR1.1_ch15.pdf",
        "full_text": "IC 6-1.1-15 Chapter 15. Procedures for Review and Appeal of Assessment and Correction of Errors.",
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_michigan_legislature_statute_pages_even_with_admin_like_code_name() -> None:
    statute = {
        "code_name": "Michigan Administrative Rules (Agentic Discovery)",
        "section_name": "MCL - Section 436.1205 - Michigan Legislature",
        "source_url": "https://www.legislature.mi.gov/Search/ExecuteSearch?sectionNumbers=436.1205&docTypes=Section",
        "full_text": "MICHIGAN LIQUOR CONTROL CODE OF 1998 (EXCERPT) Act 58 of 1998.",
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


@pytest.mark.parametrize(
    ("url", "title", "text"),
    [
        (
            "https://www.legislature.mi.gov/Laws/ChapterIndex",
            "MCL Chapter Index - Michigan Legislature",
            "Michigan Legislature chapter index. Browse the chapters of the Michigan Compiled Laws. Search statutes and public acts.",
        ),
        (
            "https://www.legislature.mi.gov/rules",
            "Error - Michigan Legislature",
            "Error page for Michigan Legislature rules route. Return to the Michigan Legislature home page.",
        ),
    ],
)
def test_rejects_michigan_legislature_index_and_rules_pages_as_rule_content(url: str, title: str, text: str) -> None:
    assert _is_substantive_rule_text(
        text=text,
        title=title,
        url=url,
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title=title,
        url=url,
    ) is False


@pytest.mark.parametrize(
    ("url", "title"),
    [
        ("https://ars.apps.lara.state.mi.us/", "ARS Public - Home"),
        ("https://ars.apps.lara.state.mi.us/Home", "ARS Public - Home"),
        ("https://ars.apps.lara.state.mi.us/AdminCode/AdminCode", "ARS Public - MI Admin Code"),
    ],
)
def test_rejects_michigan_admin_portal_home_pages_as_rule_content(url: str, title: str) -> None:
    text = (
        "Home MI Admin Code Pending/Recent Rulemaking Transactions Show 10 25 50 100 entries Search: "
        "Rule Set # Department - Bureau Rule Set Title Filing Date Effective Date 2021-48 LR Licensing and Regulatory Affairs."
    )

    assert _is_substantive_rule_text(
        text=text,
        title=title,
        url=url,
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title=title,
        url=url,
    ) is False


def test_rejects_south_dakota_codified_laws_as_admin_rule() -> None:
    statute = {
        "code_name": "South Dakota Codified Laws",
        "section_name": "Composition of State Board of Finance",
        "source_url": "https://sdlegislature.gov/api/Statutes/Statute/4-1-1",
        "full_text": "The State Board of Finance shall consist of the Governor and other officers.",
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_texas_portal_notice_as_substantive_admin_rule() -> None:
    statute = {
        "code_name": "Texas Administrative Code",
        "section_name": "Section 1.1 Texas Administrative Code (landing page)",
        "source_url": "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=LANDING_PAGE&section=1.1",
        "full_text": (
            "Section 1.1 Texas Administrative Code portal notice. "
            "Site Has Moved. You will be redirected shortly to the new site."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_indiana_iarp_home_page_as_rule_content() -> None:
    text = (
        "Indiana Administrative Rules and Policies Home Indiana Register Administrative Code MyIAR "
        "Pending Rules Upcoming Public Hearings Comment Period Deadline Register Documents Search All Site Map"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Indiana Administrative Rules and Policies | IARP",
        url="https://iar.iga.in.gov/iac//",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Indiana Administrative Rules and Policies | IARP",
        url="https://iar.iga.in.gov/iac//",
    ) is False


def test_rejects_rhode_island_subscription_page_as_rule_content() -> None:
    text = (
        "Subscribe to RICR Notifications Receive Notifications through Email Address Notification Options "
        "Select Agency Notification Frequency Daily Weekly Monthly Subscribe Manage Subscriptions"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Subscribe - Rhode Island Department of State",
        url="https://rules.sos.ri.gov/subscriptions/subscribe/all",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Subscribe - Rhode Island Department of State",
        url="https://rules.sos.ri.gov/subscriptions/subscribe/all",
    ) is False


def test_rejects_rhode_island_organizations_landing_page_as_rule_content() -> None:
    text = (
        "Welcome to the Rhode Island Code of Regulations. Table of Contents. Filter by Agency. "
        "Search Regulations. Subscribe to Notifications. FAQ. Return to top."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Welcome to the Rhode Island Code of Regulations - Rhode Island Department of State",
        url="https://rules.sos.ri.gov/Organizations",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Welcome to the Rhode Island Code of Regulations - Rhode Island Department of State",
        url="https://rules.sos.ri.gov/Organizations",
    ) is False


def test_rejects_arizona_notary_page_as_rule_content() -> None:
    text = (
        "New Notary Arizona Secretary of State commission application notary education manual oath bond "
        "commission expiration renewal and notarial acts."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="New Notary | Arizona Secretary of State",
        url="https://azsos.gov/business/notary-public/new-notary",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="New Notary | Arizona Secretary of State",
        url="https://azsos.gov/business/notary-public/new-notary",
    ) is False


def test_rejects_zhihu_discovery_noise_as_rule_content() -> None:
    text = "Administrative rules discussion thread with no state rule text or citations."

    assert _is_substantive_rule_text(
        text=text,
        title="Question thread",
        url="https://www.zhihu.com/question/19860216",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Question thread",
        url="https://www.zhihu.com/question/19860216",
    ) is False


def test_rejects_alabama_page_not_found_admin_false_positive() -> None:
    statute = {
        "code_name": "Alabama Administrative Code",
        "section_name": "Page not found | Alabama Secretary of State",
        "source_url": "https://www.sos.alabama.gov/alabama-administrative-code",
        "full_text": (
            "Page not found. Alabama Administrative Code resources and agency rules are not available at this page. "
            "Please use the secretary of state navigation and site map to continue."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_montana_history_magazine_false_positive() -> None:
    statute = {
        "code_name": "Montana Administrative Rules (Agentic Discovery)",
        "section_name": "Montana - Montana Administrative Rules (Agentic Discovery) - A1",
        "source_url": "https://mhs.mt.gov/history/montana-the-magazine-of-western-history",
        "full_text": (
            "Montana The Magazine of Western History Donate Membership Visit About Montana Heritage Center "
            "Board of Trustees Staff Directory Reviews reviewed by editors. On the cover. Vol. 10, No. 3."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_montana_board_landing_page_false_positive() -> None:
    statute = {
        "code_name": "Montana Administrative Rules (Agentic Discovery)",
        "section_name": "Home",
        "source_url": "https://bpe.mt.gov/",
        "full_text": (
            "Board of Public Education HOME BOARD MEMBERS STRATEGIC PLAN MEETING INFORMATION REPORTS "
            "AND RECOMMENDATIONS ADMINISTRATIVE RULES Public Comment Agenda Packet Events Calendar "
            "Timeline Notice of Public Hearing on Proposed Adoption."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_montana_title_inventory_page_false_positive() -> None:
    text = (
        "AGRICULTURE | Montana SOS\n"
        "Administrative Rules of Montana\n"
        "Title 4 AGRICULTURE\n"
        "Chapter 4.1 ORGANIZATIONAL RULE\n"
        "Chapter 4.2 PROCEDURAL RULES\n"
        "Chapter 4.3 AGRICULTURAL DEVELOPMENT DIVISION\n"
        "Chapter 4.4 HAIL INSURANCE PROGRAM\n"
        "Chapter 4.5 NOXIOUS WEED MANAGEMENT\n"
        "Home | Contact Us | Accessibility | Disclaimer\n"
        "Administrative Rules of Montana\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="AGRICULTURE | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/5eaf58c6-ae9f-4ebe-afe2-c617e962b390",
        min_chars=160,
    ) is False


def test_rejects_montana_subchapter_inventory_page_false_positive() -> None:
    text = (
        "HAIL INSURANCE PROGRAM | Montana SOS\n"
        "HAIL INSURANCE PROGRAM\n"
        "Subchapter 4.4.1 Organizational Rule\n"
        "Subchapter 4.4.2 Procedural Rules\n"
        "Subchapter 4.4.3 Substantive Rules\n"
        "Home | Contact Us | Accessibility | Disclaimer\n"
        "Administrative Rules of Montana\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="HAIL INSURANCE PROGRAM | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/9a3c8dd7-4528-4ad3-b2f5-bc5f0c5c31ef",
        min_chars=160,
    ) is False


def test_rejects_montana_chapter_landing_page_false_positive() -> None:
    text = (
        "ORGANIZATIONAL RULE | Montana SOS\n"
        "Administrative Rules of Montana\n"
        "Title 10 EDUCATION\n"
        "Chapter 10.1 ORGANIZATIONAL RULE\n"
        "Show Not Effective Rules\n"
        "Subchapter 10.1.1 Organizational Rule\n"
        "Home | Contact Us | Accessibility | Disclaimer\n"
        "Administrative Rules of Montana\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="ORGANIZATIONAL RULE | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/1892387a-b61e-4aa2-a1dd-d9f7a535fd42",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="ORGANIZATIONAL RULE | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/1892387a-b61e-4aa2-a1dd-d9f7a535fd42",
    ) is False


def test_synthesizes_montana_rule_urls_from_section_listing() -> None:
    text = (
        "Attorney General's Organizational and Procedural Rules Required by the Montana Administrative Procedure Act\n"
        "1.3.201 INTRODUCTION AND DEFINITIONS\n"
        "1.3.202 APPLICATION OF MONTANA ADMINISTRATIVE PROCEDURE ACT\n"
        "1.3.233 GENERAL PROVISIONS, PUBLIC INSPECTION OF ORDERS AND DECISIONS\n"
    )

    assert _candidate_montana_rule_urls_from_text(
        text=text,
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
        limit=5,
    ) == [
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/rules/1.3.201",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/rules/1.3.202",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/rules/1.3.233",
    ]


def test_rejects_montana_arm_listing_section_without_rule_detail() -> None:
    text = (
        "Attorney General's Organizational and Procedural Rules Required by the Montana Administrative Procedure Act | Montana SOS\n"
        "1.3.201 INTRODUCTION AND DEFINITIONS\n"
        "1.3.202 APPLICATION OF MONTANA ADMINISTRATIVE PROCEDURE ACT\n"
        "1.3.211 CONTESTED CASES, INTRODUCTION\n"
        "1.3.212 CONTESTED CASES, NOTICE OF OPPORTUNITY TO BE HEARD\n"
        "Home | Contact Us | Accessibility | Disclaimer\n"
        "Administrative Rules of Montana\n"
        "Show not effective\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Attorney General's Organizational and Procedural Rules Required by the Montana Administrative Procedure Act | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Attorney General's Organizational and Procedural Rules Required by the Montana Administrative Procedure Act | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
    ) is False


def test_rejects_montana_collection_root_inventory_page() -> None:
    text = (
        "Administrative Rules of Montana | Montana SOS\n"
        "Administrative Rules of Montana\n"
        "Title 1 GENERAL PROVISIONS\n"
        "Title 4 AGRICULTURE\n"
        "Title 10 EDUCATION\n"
        "Home | Contact Us | Accessibility | Disclaimer\n"
        "Emergency Rules\n"
        "Montana Administrative Register\n"
        "Show not effective\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Administrative Rules of Montana | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74",
        min_chars=160,
    ) is False


def test_accepts_montana_policy_detail_page() -> None:
    text = (
        "INTRODUCTION AND DEFINITIONS | Montana SOS\n"
        "Administrative Rules of Montana\n"
        "Montana Administrative Register\n"
        "Back\n"
        "Subchapter 1.3.2 Attorney General's Organizational and Procedural Rules Required by the Montana Administrative Procedure Act\n"
        "1.3.201 INTRODUCTION AND DEFINITIONS\n"
        "Effective\n"
        "Rule Version 27282\n"
        "Active Version\n"
        "Contact Information contactdoj@mt.gov\n"
        "Rule History Eff. 12/31/72; AMD, 2009 MAR p. 7, Eff. 1/16/09.\n"
        "Relevant MAR Notices 2008 Issue 22 Pages 2393-2539\n"
        "References 2-4-101, MCA Short Title -- Purpose -- Exception\n"
        "Referenced by 2025-195.1 Implementation of Senate Bill 315 (2025)\n"
        "Administrative Rules of Montana\n"
        "Title 1 GENERAL PROVISIONS\n"
        "Chapter 1.3 ATTORNEY GENERAL MODEL RULES\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="INTRODUCTION AND DEFINITIONS | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865",
        min_chars=160,
    ) is True


def test_accepts_montana_rule_body_page_with_arm_citations() -> None:
    text = (
        "Administrative Rules of Montana\n"
        "ARM 4.3.101 Definitions\n"
        "Authority: 80-11-102, MCA\n"
        "Implementing: 80-11-103, MCA\n"
        "(1) The department adopts the following definitions for the agricultural development division.\n"
        "History: 44-2.5.101, eff. 01/01/2024.\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Definitions | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/rules/4.3.101",
        min_chars=160,
    ) is True


def test_rejects_texas_hunting_forum_false_positive() -> None:
    statute = {
        "code_name": "Texas Administrative Rules (Agentic Discovery)",
        "section_name": "Texas Hunting Forum",
        "source_url": "https://texashuntingforum.com/rules.htm",
        "full_text": (
            "Texas Hunting Forum Guidelines / Rules of Conduct. Our forums are family friendly. "
            "We moderate to promote a PG atmosphere. Volunteer moderators enforce posting privilege rules. "
            "Back to the Texas Hunting Forum."
        ),
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_binary_pdf_payload_false_positive() -> None:
    statute = {
        "code_name": "Montana Administrative Rules (Agentic Discovery)",
        "section_name": "Chapter 1",
        "source_url": "https://mhs.mt.gov/education/Elementary/Chap1.pdf",
        "full_text": "%PDF-1.6\r%\ufffd\ufffd\ufffd\ufffd\r\n913 0 obj\r<\n>/Filter /FlateDecode /Length 928\rendobj\r",
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_montana_doc_policies_false_positive() -> None:
    statute = {
        "code_name": "Montana Administrative Rules (Agentic Discovery)",
        "section_name": "Policies",
        "source_url": "https://cor.mt.gov/DataStatsContractsPoliciesProcedures/DOCPolicies",
        "full_text": (
            "Policies. Data Stats Contracts Policies Procedures. The Montana Department of Corrections policies are public information. "
            "View the Department of Corrections Policies Manual. Additional Information Social Media Terms of Use. "
            "Administrative Rules and Notices appears in a short informational section, but the page is a policies index."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_south_dakota_boards_portal_false_positive() -> None:
    statute = {
        "code_name": "South Dakota Administrative Rules (Agentic Discovery)",
        "section_name": "Boards and Commissions",
        "source_url": "https://boardsandcommissions.sd.gov/Meetings.aspx?BoardID=123",
        "full_text": (
            "Boards and Commissions Annual Disclosure General Information Find a Board or Commission. "
            "Upcoming Meetings Archived Meetings Agenda Minutes Board Compensation."
        ),
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_legalclarity_admin_law_article_false_positive() -> None:
    statute = {
        "code_name": "South Dakota Administrative Rules (Agentic Discovery)",
        "section_name": "What Are the Functions of Administrative Law?",
        "source_url": "https://legalclarity.org/what-are-the-functions-of-administrative-law-2/",
        "full_text": (
            "Administrative law governs how agencies write rules, resolve disputes, enforce compliance, and remain subject to judicial review. "
            "The Administrative Procedure Act provides the backbone for these functions."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_federal_uscode_admin_law_false_positive() -> None:
    statute = {
        "code_name": "South Dakota Administrative Rules (Agentic Discovery)",
        "section_name": "5 USC 553: Rule making",
        "source_url": "https://uscode.house.gov/view.xhtml?req=(title:5%20section:553%20edition:prelim)",
        "full_text": (
            "5 USC 553 Rule making. This section of the Administrative Procedure Act describes notice-and-comment rulemaking for federal agencies."
        ),
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_arizona_azleg_statute_proxy_false_positive() -> None:
    statute = {
        "code_name": "Arizona Administrative Rules (Agentic Discovery)",
        "section_name": "A.R.S. 3-109",
        "source_url": "https://www.azleg.gov/viewdocument/?docName=https://www.azleg.gov/ars/3/00109-01.htm",
        "full_text": (
            "Arizona Revised Statutes 3-109. Department duties and powers. The department may adopt rules, but this page is a statute page from the Arizona Legislature."
        ),
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_accepts_relocated_arizona_rule_index_as_relaxed_recovery_text() -> None:
    text = (
        "Arizona Administrative Code. Title 1 State Government. Title 2 Administration. "
        "Title 3 Agriculture. Title 4 Professions and Occupations. Browse the official rules index, "
        "agency rules, notices, and codified administrative materials published by the Arizona Secretary of State."
    )

    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Administrative Code",
        url="https://azsos.gov/rules/arizona-administrative-code",
    ) is True


def test_candidate_links_from_html_extracts_arizona_official_chapter_document_links() -> None:
    html = """
    <html>
      <body>
        <a href="https://apps.azsos.gov/public_services/Title_01/1-01.pdf">Secretary of State - Rules and Rulemaking</a>
        <a href="https://apps.azsos.gov/public_services/Title_01/1-01.rtf">rtf</a>
      </body>
    </html>
    """

    links = _candidate_links_from_html(
        html,
        base_host="apps.azsos.gov",
        page_url="https://apps.azsos.gov/public_services/CodeTOC.htm",
        limit=4,
    )

    assert "https://apps.azsos.gov/public_services/Title_01/1-01.pdf" in links
    assert "https://apps.azsos.gov/public_services/Title_01/1-01.rtf" in links


def test_scores_arizona_official_chapter_documents_above_inventory_page() -> None:
    inventory_url = "https://apps.azsos.gov/public_services/CodeTOC.htm"
    chapter_pdf_url = "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    chapter_rtf_url = "https://apps.azsos.gov/public_services/Title_01/1-01.rtf"

    assert scraper_module._score_candidate_url(chapter_pdf_url) > scraper_module._score_candidate_url(inventory_url)
    assert scraper_module._score_candidate_url(chapter_rtf_url) > scraper_module._score_candidate_url(inventory_url)


def test_direct_detail_candidate_backlog_is_ready_for_utah_and_arizona_detail_urls() -> None:
    utah_urls = [
        f"https://adminrules.utah.gov/public/rule/R70-{index}/Current%20Rules"
        for index in ("101", "102", "103", "104")
    ]
    arizona_urls = [
        f"https://apps.azsos.gov/public_services/Title_01/1-0{index}.pdf"
        for index in range(1, 5)
    ]
    arizona_rtf_urls = [
        f"https://apps.azsos.gov/public_services/Title_01/1-0{index}.rtf"
        for index in range(1, 5)
    ]
    search_urls = [
        "https://adminrules.utah.gov/public/search/R/Current%20Rules",
        "https://apps.azsos.gov/public_services/CodeTOC.htm",
    ]

    assert scraper_module._direct_detail_candidate_backlog_is_ready(utah_urls, max_fetch=2) is True
    assert scraper_module._direct_detail_candidate_backlog_is_ready(arizona_urls, max_fetch=2) is True
    assert scraper_module._direct_detail_candidate_backlog_is_ready(arizona_rtf_urls, max_fetch=2) is True
    assert scraper_module._direct_detail_candidate_backlog_is_ready(search_urls, max_fetch=2) is False


@pytest.mark.asyncio
async def test_extract_text_from_pdf_bytes_uses_repo_pdf_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePDFProcessor:
        async def _decompose_pdf(self, pdf_path):
            assert str(pdf_path).endswith(".pdf")
            return {
                "pages": [
                    {"text_blocks": [{"content": "R1-1-101. Purpose."}, {"content": "Authority and definitions."}]},
                ]
            }

        def _extract_native_text(self, text_blocks):
            return "\n".join(block["content"] for block in text_blocks)

        async def _process_ocr(self, decomposed_content):
            return {}

    fake_pdf_module = SimpleNamespace(PDFProcessor=FakePDFProcessor)
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.processors.specialized.pdf", fake_pdf_module)

    extracted = await scraper_module._extract_text_from_pdf_bytes_with_processor(
        b"%PDF-1.4 fake pdf bytes",
        source_url="https://apps.azsos.gov/public_services/Title_01/1-01.pdf",
    )

    assert "R1-1-101. Purpose." in extracted
    assert "Authority and definitions." in extracted


@pytest.mark.asyncio
async def test_extract_text_from_rtf_bytes_uses_repo_rtf_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRTFResult:
        success = True
        text = "R1-1-101. RTF extracted rule text."

    class FakeRTFExtractor:
        def extract(self, file_path):
            assert str(file_path).endswith(".rtf")
            return FakeRTFResult()

    monkeypatch.setattr(file_converter_module, "RTFExtractor", FakeRTFExtractor)

    extracted = await scraper_module._extract_text_from_rtf_bytes_with_processor(
        b"{\\rtf1\\ansi R1-1-101. RTF extracted rule text.}",
        source_url="https://example.gov/rules/current.rtf",
    )

    assert extracted == "R1-1-101. RTF extracted rule text."


@pytest.mark.asyncio
async def test_extract_text_from_rtf_bytes_falls_back_without_striprtf(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRTFResult:
        success = False
        text = ""

    class FakeRTFExtractor:
        def extract(self, file_path):
            return FakeRTFResult()

    monkeypatch.setattr(file_converter_module, "RTFExtractor", FakeRTFExtractor)

    extracted = await scraper_module._extract_text_from_rtf_bytes_with_processor(
        b"{\\rtf1\\ansi R1-1-101.\\par Authority and definitions.}",
        source_url="https://example.gov/rules/current.rtf",
    )

    assert "R1-1-101." in extracted
    assert "Authority and definitions." in extracted


@pytest.mark.asyncio
async def test_scrape_pdf_candidate_url_uses_playwright_download_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 403
        headers = {"content-type": "text/html; charset=UTF-8"}
        content = b"<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"

    async def fake_download(url: str):
        return {
            "body": b"%PDF-1.4 fake pdf bytes",
            "content_type": "application/pdf",
            "suggested_filename": "1-01.pdf",
        }

    async def fake_extract(pdf_bytes: bytes, *, source_url: str):
        assert pdf_bytes.startswith(b"%PDF-")
        return "R1-1-101. Purpose. Authority and definitions."

    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_playwright", fake_download)
    monkeypatch.setattr(scraper_module, "_extract_text_from_pdf_bytes_with_processor", fake_extract)

    scraped = await scraper_module._scrape_pdf_candidate_url_with_processor(
        "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    )

    assert scraped is not None
    assert scraped.method_used == "pdf_processor_playwright_download"
    assert "Authority and definitions." in scraped.text


def test_download_document_bytes_via_cloudscraper_returns_binary_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        content = b"%PDF-1.4 fake pdf bytes"

    class FakeScraper:
        def get(self, url, timeout=0, headers=None):
            assert url == "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
            assert headers is not None
            return FakeResponse()

    class FakeCloudscraperModule:
        @staticmethod
        def create_scraper(browser=None):
            assert browser is not None
            return FakeScraper()

    monkeypatch.setitem(sys.modules, "cloudscraper", FakeCloudscraperModule)

    fetched = scraper_module._download_document_bytes_via_cloudscraper(
        "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    )

    assert fetched == {
        "body": b"%PDF-1.4 fake pdf bytes",
        "content_type": "application/pdf",
        "suggested_filename": "1-01.pdf",
    }


@pytest.mark.asyncio
async def test_download_document_bytes_via_page_fetch_returns_binary_bytes() -> None:
    class FakePage:
        async def evaluate(self, script, url):
            assert "fetch(targetUrl" in script
            assert url == "https://apps.azsos.gov/public_services/Title_01/1-01.rtf"
            return {
                "ok": True,
                "status": 200,
                "contentType": "application/rtf",
                "contentDisposition": "",
                "bodyBytes": [123, 92, 114, 116, 102, 49],
            }

    fetched = await scraper_module._download_document_bytes_via_page_fetch(
        FakePage(),
        "https://apps.azsos.gov/public_services/Title_01/1-01.rtf",
    )

    assert fetched == {
        "body": b"{\\rtf1",
        "content_type": "application/rtf",
        "suggested_filename": "1-01.rtf",
    }


@pytest.mark.asyncio
async def test_scrape_pdf_candidate_url_uses_cloudscraper_before_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 403
        headers = {"content-type": "text/html; charset=UTF-8"}
        content = b"<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"

    def fake_cloudscraper(url: str):
        return {
            "body": b"%PDF-1.4 fake pdf bytes",
            "content_type": "application/pdf",
            "suggested_filename": "1-01.pdf",
        }

    async def fake_playwright(url: str):
        raise AssertionError("playwright fallback should not be used when cloudscraper succeeds")

    async def fake_extract(pdf_bytes: bytes, *, source_url: str):
        assert pdf_bytes.startswith(b"%PDF-")
        return "R1-1-101. Purpose. Authority and definitions."

    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_cloudscraper", fake_cloudscraper)
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_playwright", fake_playwright)
    monkeypatch.setattr(scraper_module, "_extract_text_from_pdf_bytes_with_processor", fake_extract)

    scraped = await scraper_module._scrape_pdf_candidate_url_with_processor(
        "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    )

    assert scraped is not None
    assert scraped.method_used == "pdf_processor_cloudscraper"


def test_playwright_persistent_profile_dir_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_PLAYWRIGHT_PERSISTENT_PROFILE_DIR", "/tmp/copilot-playwright-profile")

    assert scraper_module._playwright_persistent_profile_dir().as_posix() == "/tmp/copilot-playwright-profile"


def test_playwright_persistent_profile_mode_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_PLAYWRIGHT_USE_PERSISTENT_PROFILE", raising=False)

    assert scraper_module._use_persistent_playwright_profile() is True


def test_playwright_headless_mode_can_be_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_PLAYWRIGHT_HEADLESS", "0")

    assert scraper_module._playwright_headless_enabled() is False


@pytest.mark.asyncio
async def test_scrape_rtf_candidate_url_uses_playwright_download_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 403
        headers = {"content-type": "text/html; charset=UTF-8"}
        content = b"<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"

    async def fake_download(url: str):
        return {
            "body": b"{\\rtf1\\ansi R1-1-101.\\par Authority and definitions.}",
            "content_type": "application/rtf",
            "suggested_filename": "1-01.rtf",
        }

    async def fake_extract(rtf_bytes: bytes, *, source_url: str):
        assert b"\\rtf1" in rtf_bytes
        return "R1-1-101. Authority and definitions."

    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_playwright", fake_download)
    monkeypatch.setattr(scraper_module, "_extract_text_from_rtf_bytes_with_processor", fake_extract)

    scraped = await scraper_module._scrape_rtf_candidate_url_with_processor(
        "https://apps.azsos.gov/public_services/Title_01/1-01.rtf"
    )

    assert scraped is not None
    assert scraped.method_used == "rtf_processor_playwright_download"
    assert "Authority and definitions." in scraped.text


@pytest.mark.asyncio
async def test_scrape_utah_rule_detail_via_public_download_uses_html_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, *, status_code=200, headers=None, text="", json_data=None, content=b""):
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text
            self._json_data = json_data
            self.content = content or text.encode("utf-8")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise scraper_module.requests.HTTPError(f"status {self.status_code}")

        def json(self):
            return self._json_data

    def fake_get(url, timeout=0, headers=None):
        if "searchRuleDataTotal/R70-101/Current%20Rules" in url:
            return FakeResponse(
                json_data=[
                    {
                        "programs": [
                            {
                                "rules": [
                                    {
                                        "referenceNumber": "R70-101",
                                        "name": "Bedding, Upholstered Furniture, and Quilted Clothing",
                                        "htmlDownload": "uac-html/test-rule.html",
                                        "htmlDownloadName": "R70-101.html",
                                        "pdfDownload": "uac-pdf/test-rule.pdf",
                                        "pdfDownloadName": "R70-101.pdf",
                                        "linkToRule": "R70-101/Current Rules",
                                    }
                                ]
                            }
                        ]
                    }
                ]
            )
        if "api/public/getfile/uac-html/test-rule.html/R70-101.html" in url:
            return FakeResponse(
                headers={"content-type": "text/html"},
                text="<html><body><h1>R70-101. Bedding</h1><p>R70-101-1. Authority and Purpose.</p><p>The rule text.</p></body></html>",
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    scraped = await scraper_module._scrape_utah_rule_detail_via_public_download(
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules?searchText=R70"
    )

    assert scraped is not None
    assert scraped.method_used == "utah_public_getfile_html"
    assert "R70-101-1. Authority and Purpose." in scraped.text
    assert scraped.title == "R70-101. Bedding, Upholstered Furniture, and Quilted Clothing"


def test_accepts_new_hampshire_archived_rule_chapter() -> None:
    statute = {
        "code_name": "New Hampshire Administrative Rules (Agentic Discovery)",
        "section_name": "Agr 500",
        "source_url": "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr500.html",
        "full_text": (
            "CHAPTER Agr 500 WEEKLY MARKET BULLETIN Statutory Authority: RSA 425:21-a, RSA 541-A:16, I(b). "
            "PART Agr 501 WEEKLY MARKET BULLETIN PURPOSE AND DEFINITIONS. Source. #6039, eff 7-1-95."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is True
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_accepts_texas_transfer_page_as_substantive_admin_rule() -> None:
    statute = {
        "code_name": "Texas Administrative Rules (Agentic Discovery)",
        "section_name": "Texas Department on Aging Rule Transfer",
        "source_url": "https://www.sos.state.tx.us/texreg/transfers/aging091004.html",
        "full_text": (
            "Texas Department on Aging Rule Transfer. Through the enactment of House Bill 2292, 78th Legislature, "
            "the administrative rules of the legacy agencies will transfer either to a new agency or to HHSC. "
            "All TDoA administrative rules will be transferred from Title 40, Part 9 of the Texas Administrative Code "
            "to DADS and reorganized under Title 40, Part 1. The transfer is effective September 1, 2004. "
            "Please refer to Figure: 40 TAC Part 9 for the complete conversion chart. TRD-200405434"
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is True


def test_accepts_south_dakota_official_rule_index_page() -> None:
    statute = {
        "code_name": "South Dakota Administrative Rules (Agentic Discovery)",
        "section_name": "Administrative Rules | South Dakota Legislature",
        "source_url": "https://sdlegislature.gov/Rules/Administrative",
        "full_text": (
            "Administrative Rules List Current Register Archived Registers Administrative Rules Manual Rules Review Committee. "
            "Administrative Rules Home Administrative Rules Go To: 01:15 02:01 02:02 05:01 10:01 12:01 17:10 20:01 24:03 41:01 44:02 67:10 74:02."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is True
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_rejects_utah_official_rule_index_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Utah Administrative Rules (Agentic Discovery)",
        "section_name": "Administrative Code Updates | Office of Administrative Rules",
        "source_url": "https://rules.utah.gov/publications/code-updates",
        "full_text": (
            "Administrative Code Updates. Office of Administrative Rules. Utah Administrative Code updates and changed rule files. "
            "Titles of the Utah Administrative Code are arranged by the authoring department. "
            "For example, R15 is the title of the code that contains the rules written by the Office of Administrative Rules."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_rejects_utah_adminrules_search_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Utah Administrative Rules (Agentic Discovery)",
        "section_name": "Utah Office of Administrative Rules",
        "source_url": "https://adminrules.utah.gov/public/search",
        "full_text": (
            "Administrative Rules Search Current Rules Proposed Rules Emergency Rules. "
            "Agency Agriculture and Food 8 results. Agency Commerce 7 results. "
            "Administrative Code search current rules by agency and rule."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_rejects_utah_current_rules_search_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Utah Administrative Rules (Agentic Discovery)",
        "section_name": "Utah Office of Administrative Rules",
        "source_url": "https://adminrules.utah.gov/public/search//Current%20Rules",
        "full_text": (
            "Administrative Rules Search Current Rules Proposed Rules Emergency Rules. "
            "Agency Agriculture and Food 8 results. Agency Commerce 7 results. "
            "Administrative Code search current rules by agency and rule."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_rejects_utah_root_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Utah Administrative Rules (Agentic Discovery)",
        "section_name": "Office of Administrative Rules",
        "source_url": "https://rules.utah.gov",
        "full_text": (
            "Office of Administrative Rules. Administrative Code. Publications. Utah State Bulletin. "
            "Administrative Rules Register. Contact Agency. Rulewriting Manual."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_accepts_utah_rule_detail_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Utah Administrative Rules (Agentic Discovery)",
        "section_name": "R70-101. Administration of Utah Educational Savings Plan",
        "source_url": "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules?searchText=undefined",
        "full_text": (
            "R70-101. Administration of Utah Educational Savings Plan. "
            "Authority and Purpose. Definitions. Eligibility. Board duties. Account owner rights. Contributions. "
            "Withdrawals. Penalties. "
        )
        * 12,
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is True
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_rejects_utah_erules_category_news_page_as_rule_text() -> None:
    text = (
        "eRules | Office of Administrative Rules. RulesNews Office of Administrative Rules News and information directly "
        "from the Office of Administrative Rules. To get notified via email on new versions of the Utah State Bulletin "
        "or Utah State Digest, visit Subscriptions. Changes to Utah Administrative Code Links."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="eRules | Office of Administrative Rules",
        url="https://rules.utah.gov/category/erules/",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="eRules | Office of Administrative Rules",
        url="https://rules.utah.gov/category/erules/",
    ) is False


def test_rejects_utah_rulesnews_page_as_rule_text() -> None:
    text = (
        "News | Office of Administrative Rules. RulesNews Office of Administrative Rules News and information directly "
        "from the Office of Administrative Rules. To get notified via email on new versions of the Utah State Bulletin "
        "or Utah State Digest, visit Subscriptions. Changes to Utah Administrative Code Links."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="News | Office of Administrative Rules",
        url="https://rules.utah.gov/rulesnews",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="News | Office of Administrative Rules",
        url="https://rules.utah.gov/rulesnews",
    ) is False


def test_rejects_utah_link_migration_news_post_as_rule_text() -> None:
    text = (
        "Changes to Utah Administrative Code Links | Office of Administrative Rules. Hi, rule readers! We're continuing "
        "our transition to the new eRules Utah Administrative Code public portal found at adminrules.utah.gov. "
        "To get notified via email on new versions of the Utah State Bulletin or Utah State Digest, visit Subscriptions."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Changes to Utah Administrative Code Links | Office of Administrative Rules",
        url="https://rules.utah.gov/changes-to-utah-administrative-code-links-2/",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Changes to Utah Administrative Code Links | Office of Administrative Rules",
        url="https://rules.utah.gov/changes-to-utah-administrative-code-links-2/",
    ) is False


def test_rejects_utah_bulletin_announcement_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Utah Administrative Rules (Agentic Discovery)",
        "section_name": "November 1, 2025, issue of the Utah State Bulletin is now available | Office of Administrative Rules",
        "source_url": "https://rules.utah.gov/wp-content/uploads/b20251101.pdf",
        "full_text": (
            "November 1, 2025, issue of the Utah State Bulletin is now available. "
            "The November 1, 2025, issue of the Utah State Bulletin is available online. "
        )
        * 20,
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_utah_adminrules_home_landing_page() -> None:
    statute = {
        "code_name": "Utah Administrative Rules (Agentic Discovery)",
        "section_name": "Utah Office of Administrative Rules",
        "source_url": "https://adminrules.utah.gov/public/home",
        "full_text": (
            "HOME CODE BULLETIN HELP ABOUT US CONTACT US. "
            "The state of Utah eRules application provides state agencies the ability to electronically submit proposed rule packets. "
            "Questions about the content or application of a particular administrative rule must be referred to the agency that issued the rule."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_indiana_current_code_index_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Indiana Administrative Rules (Agentic Discovery)",
        "section_name": "Indiana Administrative Code | IARP",
        "source_url": "https://iar.iga.in.gov/code/current",
        "full_text": (
            "Indiana Administrative Code Current TITLE 10 Office of Attorney General for the State TITLE 11 Consumer Protection Division of the Office of the Attorney General "
            "TITLE 15 State Election Board TITLE 16 Office of the Lieutenant Governor TITLE 18 Indiana Election Commission TITLE 20 State Board of Accounts "
            "TITLE 25 Indiana Department of Administration TITLE 30 State Personnel Board TITLE 31 State Personnel Department TITLE 33 State Employees' Appeals Commission."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_accepts_indiana_article_detail_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Indiana Administrative Rules (Agentic Discovery)",
        "section_name": "Title 10, Article 1.5",
        "short_title": "Title 10, Article 1.5",
        "source_url": "https://iar.iga.in.gov/code/current/10/1.5",
        "full_text": (
            "TITLE 10 Office of Attorney General ARTICLE 1.5 authority effective section rule law "
            "Sec. 1. The commissioner may adopt rules to administer the chapter. "
            "Authority: IC 4-22-2-13; IC 4-6-2-1. Affected: IC 4-22-2; IC 4-6-1. "
            "This rule governs agency procedures, notice requirements, filing obligations, and enforcement."
        ),
        "legal_area": "administrative",
        "official_cite": "IN Admin Rule A1",
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=100) is True


def test_candidate_utah_rule_urls_from_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": 2,
            "name": "Agriculture and Food",
            "programs": [
                {
                    "id": 70,
                    "name": "Regulatory Services",
                    "rules": [
                        {
                            "referenceNumber": "R70-101",
                            "linkToRule": "R70-101/Current Rules",
                            "htmlDownload": "uac-html/d605db48-0f6b-40d7-84a9-9a50c715d637.html",
                        },
                        {
                            "referenceNumber": "R70-201",
                            "linkToRule": "R70-201/Current Rules",
                            "htmlDownload": "uac-html/abc44f4f-93bc-4f1f-8c5d-cd234ca8fb3d.html",
                        },
                    ],
                }
            ],
        }
    ]

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    observed: dict[str, object] = {}

    def _fake_get(*args, **kwargs):
        observed["url"] = args[0] if args else kwargs.get("url")
        observed["headers"] = kwargs.get("headers") or {}
        return _FakeResponse()

    monkeypatch.setattr(scraper_module.requests, "get", _fake_get)

    urls = _candidate_utah_rule_urls_from_public_api(
        url="https://adminrules.utah.gov/public/search//Current%20Rules",
        limit=4,
    )

    assert observed["url"] == "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules"
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert headers.get("Accept") == "application/json, text/plain, */*"

    assert urls == [
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules",
        "https://adminrules.utah.gov/public/rule/R70-201/Current%20Rules",
    ]


def test_candidate_utah_rule_urls_from_public_api_preserves_explicit_query(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return []

    observed: dict[str, object] = {}

    def _fake_get(*args, **kwargs):
        observed["url"] = args[0] if args else kwargs.get("url")
        return _FakeResponse()

    monkeypatch.setattr(scraper_module.requests, "get", _fake_get)

    urls = _candidate_utah_rule_urls_from_public_api(
        url="https://adminrules.utah.gov/public/search/R70-101/Current%20Rules",
        limit=4,
    )

    assert urls == []
    assert observed["url"] == "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R70-101/Current%20Rules"


def test_candidate_utah_rule_urls_from_public_api_accepts_api_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "programs": [
                {
                    "rules": [
                        {
                            "referenceNumber": "R70-101",
                            "linkToRule": "R70-101/Current Rules",
                        }
                    ]
                }
            ]
        }
    ]

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    observed: dict[str, object] = {}

    def _fake_get(*args, **kwargs):
        observed["url"] = args[0] if args else kwargs.get("url")
        return _FakeResponse()

    monkeypatch.setattr(scraper_module.requests, "get", _fake_get)

    urls = _candidate_utah_rule_urls_from_public_api(
        url="https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules",
        limit=4,
    )

    assert observed["url"] == "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules"
    assert urls == [
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules",
    ]


def test_initial_pending_candidates_prioritize_seed_expansions() -> None:
    ranked_urls = [
        ("https://adminrules.utah.gov/public/search/A/Current%20Rules", 4),
        ("https://adminrules.utah.gov/public/search/B/Current%20Rules", 4),
        ("https://adminrules.utah.gov/public/search/C/Current%20Rules", 4),
        ("https://adminrules.utah.gov/public/search/D/Current%20Rules", 4),
    ]
    seed_expansion_candidates = [
        ("https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules", 10),
    ]

    pending = scraper_module._build_initial_pending_candidates(
        ranked_urls=ranked_urls,
        seed_expansion_candidates=seed_expansion_candidates,
        max_candidates=4,
    )

    assert pending[0] == (
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules",
        10,
    )
    assert pending[1:] == ranked_urls


def test_score_candidate_url_prioritizes_utah_detail_pages_over_search_indexes() -> None:
    detail_score = scraper_module._score_candidate_url(
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules"
    )
    search_score = scraper_module._score_candidate_url(
        "https://adminrules.utah.gov/public/search/R/Current%20Rules"
    )

    assert detail_score > search_score


def test_prefers_live_fetch_for_utah_detail_pages() -> None:
    assert (
        scraper_module._prefers_live_fetch(
            "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules"
        )
        is True
    )
    assert scraper_module._prefers_live_fetch("https://rules.utah.gov/") is False


def test_seed_expansion_backlog_is_ready_after_enough_unique_detail_urls() -> None:
    seed_expansion_candidates = [
        (f"https://adminrules.utah.gov/public/rule/R70-{index}/Current%20Rules", 12)
        for index in range(100, 112)
    ]
    seed_expansion_candidates.append(
        ("https://adminrules.utah.gov/public/rule/R70-100/Current%20Rules", 12)
    )

    assert scraper_module._seed_expansion_backlog_is_ready(seed_expansion_candidates, max_fetch=3) is True
    assert scraper_module._seed_expansion_backlog_is_ready(seed_expansion_candidates[:3], max_fetch=3) is False


def test_candidate_utah_rule_urls_from_public_api_skips_html_download_shell_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = [
        {
            "id": 2,
            "name": "Agriculture and Food",
            "programs": [
                {
                    "id": 70,
                    "name": "Regulatory Services",
                    "rules": [
                        {
                            "referenceNumber": "R70-101",
                            "linkToRule": "R70-101/Current Rules",
                            "htmlDownload": "uac-html/d605db48-0f6b-40d7-84a9-9a50c715d637.html",
                        }
                    ],
                }
            ],
        }
    ]

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: _FakeResponse())

    urls = _candidate_utah_rule_urls_from_public_api(
        url="https://adminrules.utah.gov/public/search//Current%20Rules",
        limit=4,
    )

    assert urls == [
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules",
    ]


def test_utah_discovery_host_allowlist_excludes_external_domains() -> None:
    allowed_hosts = _allowed_discovery_hosts_for_state("UT", "Utah")

    assert "rules.utah.gov" in allowed_hosts
    assert "adminrules.utah.gov" in allowed_hosts
    assert _url_allowed_for_state("https://rules.utah.gov/publications/code-updates/", allowed_hosts) is True
    assert _url_allowed_for_state("https://adminrules.utah.gov/public/search", allowed_hosts) is True
    assert _url_allowed_for_state("https://www.nationalgeographic.com/travel/national-parks/article/zion-national-park", allowed_hosts) is False


def test_candidate_links_from_html_keeps_utah_detail_link_on_allowed_sibling_host() -> None:
    allowed_hosts = _allowed_discovery_hosts_for_state("UT", "Utah")
    html = (
        '<a href="https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules?searchText=undefined">'
        'Bedding, Upholstered Furniture, and Quilted Clothing(101)</a>'
        '<a href="https://example.com/not-allowed">Off domain</a>'
    )

    assert _candidate_links_from_html(
        html,
        base_host="rules.utah.gov",
        page_url="https://rules.utah.gov/utah-administrative-code/",
        limit=5,
        allowed_hosts=allowed_hosts,
    ) == [
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules?searchText=undefined",
    ]


@pytest.mark.anyio
async def test_agentic_discovery_ignores_off_domain_search_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    keep_url = "https://rules.utah.gov/publications/code-updates/"
    reject_url = "https://www.nationalgeographic.com/travel/national-parks/article/zion-national-park"

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": [{"url": reject_url}, {"url": keep_url}]}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text="Administrative Code Updates. Utah Administrative Code updates and changed rule files.",
                title="Administrative Code Updates | Office of Administrative Rules",
                html="",
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(
                text="Administrative Code Updates. Utah Administrative Code updates and changed rule files.",
                title="Administrative Code Updates | Office of Administrative Rules",
                html="",
                links=[],
            )

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [keep_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: True)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(unified_web_scraper_module, "ScraperConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        unified_web_scraper_module,
        "ScraperMethod",
        SimpleNamespace(
            COMMON_CRAWL="common_crawl",
            WAYBACK_MACHINE="wayback_machine",
            PLAYWRIGHT="playwright",
            BEAUTIFULSOUP="beautifulsoup",
            REQUESTS_ONLY="requests_only",
        ),
    )

    result = await _agentic_discover_admin_state_blocks(
        states=["UT"],
        max_candidates_per_state=5,
        max_fetch_per_state=2,
        max_results_per_domain=5,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert [statute["source_url"] for statute in result["state_blocks"][0]["statutes"]] == [keep_url]


@pytest.mark.anyio
async def test_agentic_discovery_seed_fetch_uses_initialized_max_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_calls = {"count": 0}

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            fetch_calls["count"] += 1
            document = SimpleNamespace(
                text="Official Alabama administrative rules body with authority and chapter text.",
                title="Alabama Administrative Code",
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    class _FakeParallelWebArchiver:
        def __init__(self, **kwargs):
            pass

        async def archive_urls_parallel(self, urls):
            return []

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(text="", title="", links=[])

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: ["https://admincode.legislature.state.al.us/administrative-code"])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: True)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedFetchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(unified_web_scraper_module, "ScraperConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        unified_web_scraper_module,
        "ScraperMethod",
        SimpleNamespace(
            COMMON_CRAWL="common_crawl",
            WAYBACK_MACHINE="wayback_machine",
            PLAYWRIGHT="playwright",
            BEAUTIFULSOUP="beautifulsoup",
            REQUESTS_ONLY="requests_only",
        ),
    )

    result = await _agentic_discover_admin_state_blocks(
        states=["AL"],
        max_candidates_per_state=5,
        max_fetch_per_state=1,
        max_results_per_domain=5,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert result["state_blocks"][0]["statutes"][0]["source_url"] == "https://admincode.legislature.state.al.us/administrative-code"
    assert fetch_calls["count"] >= 1


@pytest.mark.anyio
async def test_agentic_discovery_short_circuits_utah_api_rule_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules"
    rule_url = "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules"
    agentic_discovery_calls = 0

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            nonlocal agentic_discovery_calls
            agentic_discovery_calls += 1
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text="Utah rules search shell.",
                title="Utah Administrative Rules Search",
                html="",
                extraction_provenance={"method": "requests_only"},
            )
            return SimpleNamespace(document=document)

    class _FakeParallelWebArchiver:
        def __init__(self, **kwargs):
            pass

        async def archive_urls_parallel(self, urls):
            return []

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(text="", title="", html="", links=[])

    async def _fake_scrape_utah_rule_detail_via_public_download(url: str):
        if url != rule_url:
            return None
        return SimpleNamespace(
            url=url,
            title="R70-101. Bedding, Upholstered Furniture, and Quilted Clothing",
            text="R70-101. Bedding, Upholstered Furniture, and Quilted Clothing. Authority and purpose. History. Implementing.",
            html="",
            links=[],
            success=True,
            method_used="utah_public_getfile_html",
            extraction_provenance={"method": "utah_public_getfile_html"},
        )

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_candidate_utah_rule_urls_from_public_api", lambda url, limit=24: [rule_url])
    monkeypatch.setattr(scraper_module, "_scrape_utah_rule_detail_via_public_download", _fake_scrape_utah_rule_detail_via_public_download)
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") == rule_url)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: False)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedFetchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(unified_web_scraper_module, "ScraperConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        unified_web_scraper_module,
        "ScraperMethod",
        SimpleNamespace(
            COMMON_CRAWL="common_crawl",
            WAYBACK_MACHINE="wayback_machine",
            PLAYWRIGHT="playwright",
            BEAUTIFULSOUP="beautifulsoup",
            REQUESTS_ONLY="requests_only",
        ),
    )

    result = await _agentic_discover_admin_state_blocks(
        states=["UT"],
        max_candidates_per_state=5,
        max_fetch_per_state=1,
        max_results_per_domain=5,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert result["state_blocks"][0]["statutes"][0]["source_url"] == rule_url
    assert agentic_discovery_calls == 0
    assert result["report"]["UT"]["format_counts"]["html"] == 1
    assert result["report"]["UT"]["gap_summary"]["rule_hosts"] == ["adminrules.utah.gov"]


@pytest.mark.anyio
async def test_agentic_discovery_does_not_spend_full_budget_in_utah_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules"
    rule_urls = [
        f"https://adminrules.utah.gov/public/rule/R70-10{index}/Current%20Rules"
        for index in range(1, 5)
    ]
    now = {"value": 0.0}
    prefetch_calls = {"count": 0}

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text="Utah rules search shell.",
                title="Utah Administrative Rules Search",
                html="",
                extraction_provenance={"method": "requests_only"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            if url in rule_urls:
                return SimpleNamespace(
                    text="R70-101. Utah administrative rule text with authority, purpose, and implementation sections.",
                    title="R70-101. Utah Rule",
                    html="",
                    links=[],
                    method_used="playwright",
                    extraction_provenance={"method": "playwright"},
                )
            return SimpleNamespace(text="", title="", html="", links=[])

    async def _fake_scrape_utah_rule_detail_via_public_download(url: str):
        prefetch_calls["count"] += 1
        if prefetch_calls["count"] <= len(rule_urls):
            now["value"] += 30.0
            return None
        return None

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_candidate_utah_rule_urls_from_public_api", lambda url, limit=24: list(rule_urls))
    monkeypatch.setattr(scraper_module, "_scrape_utah_rule_detail_via_public_download", _fake_scrape_utah_rule_detail_via_public_download)
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") in rule_urls)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: False)
    monkeypatch.setattr(scraper_module.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(unified_web_scraper_module, "ScraperConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        unified_web_scraper_module,
        "ScraperMethod",
        SimpleNamespace(
            COMMON_CRAWL="common_crawl",
            WAYBACK_MACHINE="wayback_machine",
            PLAYWRIGHT="playwright",
            BEAUTIFULSOUP="beautifulsoup",
            REQUESTS_ONLY="requests_only",
        ),
    )

    result = await _agentic_discover_admin_state_blocks(
        states=["UT"],
        max_candidates_per_state=8,
        max_fetch_per_state=4,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] >= 1
    assert result["report"]["UT"]["inspected_urls"] >= 1


@pytest.mark.anyio
async def test_scrape_state_admin_rules_recovers_missing_target_state_via_agentic(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape_state_laws(**kwargs):
        return {
            "status": "success",
            "data": [],
            "metadata": {"states_scraped": kwargs.get("states") or []},
        }

    async def _fake_agentic_discover_admin_state_blocks(**kwargs):
        return {
            "status": "success",
            "state_blocks": [
                {
                    "state_code": "AL",
                    "state_name": "Alabama",
                    "title": "Alabama Administrative Rules",
                    "source": "Agentic web-archive discovery",
                    "source_url": "https://admincode.legislature.state.al.us/administrative-code",
                    "scraped_at": "2026-03-08T00:00:00",
                    "statutes": [
                        {
                            "state_code": "AL",
                            "state_name": "Alabama",
                            "statute_id": "AL-AGENTIC-A1",
                            "code_name": "Alabama Administrative Rules (Agentic Discovery)",
                            "section_number": "A1",
                            "section_name": "Alabama Administrative Code",
                            "short_title": "Alabama Administrative Code",
                            "full_text": "Alabama Administrative Code agency list and chapter links.",
                            "summary": "Alabama Administrative Code agency list and chapter links.",
                            "legal_area": "administrative",
                            "source_url": "https://admincode.legislature.state.al.us/administrative-code",
                            "official_cite": "AL Admin Rule A1",
                            "structured_data": {"type": "regulation", "agentic_discovery": True},
                        }
                    ],
                    "rules_count": 1,
                    "schema_version": "1.0",
                    "normalized": True,
                }
            ],
            "kg_rows": [],
            "report": {"AL": {"rules_count": 1}},
        }

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scrape_state_admin_rules(
        states=["AL"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=True,
        require_substantive_rule_text=True,
    )

    assert result["status"] == "success"
    assert len(result["data"]) == 1
    assert result["data"][0]["state_code"] == "AL"
    assert result["data"][0]["rules_count"] == 1
    assert result["metadata"]["agentic_recovered_states"] == ["AL"]
    assert result["metadata"]["missing_rule_states"] == []


@pytest.mark.anyio
async def test_agentic_discovery_seed_fetch_expands_hydrated_seed_links(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://iar.iga.in.gov/code"
    deep_url = "https://iar.iga.in.gov/code/current/10/1"
    seed_text = (
        "Indiana Administrative Code Current "
        "TITLE 10 Office of Attorney General for the State "
        "TITLE 11 Consumer Protection Division of the Office of the Attorney General "
        "TITLE 15 State Election Board TITLE 16 Office of the Lieutenant Governor "
        "TITLE 18 Indiana Election Commission TITLE 20 State Board of Accounts "
        "TITLE 25 Indiana Department of Administration TITLE 30 State Personnel Board "
        "TITLE 31 State Personnel Department TITLE 33 State Employees' Appeals Commission."
    )

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text=seed_text,
                title="Indiana Administrative Code | IARP",
                html="<html><body><div id='root'></div></body></html>",
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            if url == seed_url:
                return SimpleNamespace(
                    text=seed_text,
                    title="Indiana Administrative Code | IARP",
                    html="<a href='https://iar.iga.in.gov/code/current/10/1'>Article 1</a>",
                    links=[{"url": deep_url, "text": "Article 1"}],
                )
            return SimpleNamespace(
                text="TITLE 10 Office of Attorney General ARTICLE 1 UNCLAIMED PROPERTY authority effective section.",
                title="Title 10, Article 1",
                html="",
                links=[],
            )

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: True)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(unified_web_scraper_module, "ScraperConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        unified_web_scraper_module,
        "ScraperMethod",
        SimpleNamespace(
            COMMON_CRAWL="common_crawl",
            WAYBACK_MACHINE="wayback_machine",
            PLAYWRIGHT="playwright",
            BEAUTIFULSOUP="beautifulsoup",
            REQUESTS_ONLY="requests_only",
        ),
    )

    result = await _agentic_discover_admin_state_blocks(
        states=["IN"],
        max_candidates_per_state=5,
        max_fetch_per_state=3,
        max_results_per_domain=5,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 2
    assert [
        statute["source_url"] for statute in result["state_blocks"][0]["statutes"]
    ] == [seed_url, deep_url]


@pytest.mark.anyio
async def test_agentic_discovery_follows_live_prioritized_seed_links(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://iar.iga.in.gov/code/current"
    deep_url = "https://iar.iga.in.gov/code/current/10/1.5"
    deep_text = (
        "TITLE 10 Office of Attorney General ARTICLE 1.5 authority effective section rule law "
        "Sec. 1. The commissioner may adopt rules to administer the chapter. "
        "Authority: IC 4-22-2-13; IC 4-6-2-1. Affected: IC 4-22-2; IC 4-6-1. "
        "This rule governs agency procedures, notice requirements, filing obligations, and enforcement."
    )
    hydrated_text = (
        "Indiana Administrative Code Current "
        "TITLE 10 Office of Attorney General for the State "
        "TITLE 11 Consumer Protection Division of the Office of the Attorney General "
        "TITLE 15 State Election Board TITLE 16 Office of the Lieutenant Governor "
        "TITLE 18 Indiana Election Commission TITLE 20 State Board of Accounts "
        "TITLE 25 Indiana Department of Administration TITLE 30 State Personnel Board "
        "TITLE 31 State Personnel Department TITLE 33 State Employees' Appeals Commission."
    )

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text="Indiana Register. You need to enable JavaScript to run this app.",
                title="Indiana Register",
                html="<div id='root'></div>",
                extraction_provenance={"method": "beautifulsoup"},
            )
            return SimpleNamespace(document=document)

    class _GenericScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(
                text="Indiana Register. You need to enable JavaScript to run this app.",
                title="Indiana Register",
                html="<div id='root'></div>",
                links=[],
            )

    class _LiveScraper(_GenericScraper):
        async def scrape(self, url: str):
            if url == seed_url:
                return SimpleNamespace(
                    text=hydrated_text,
                    title="Indiana Administrative Code | IARP",
                    html=f"<a href='{deep_url}'>Article 1.5</a>",
                    links=[{"url": deep_url, "text": "Article 1.5"}],
                )
            return SimpleNamespace(
                text=deep_text,
                title="Title 10, Article 1.5",
                html="",
                links=[],
            )

    def _fake_scraper_factory(cfg):
        preferred = list(getattr(cfg, "preferred_methods", []) or [])
        if preferred and preferred[0] == "playwright":
            return _LiveScraper(cfg)
        return _GenericScraper(cfg)

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _fake_scraper_factory)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(unified_web_scraper_module, "ScraperConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(
        unified_web_scraper_module,
        "ScraperMethod",
        SimpleNamespace(
            COMMON_CRAWL="common_crawl",
            WAYBACK_MACHINE="wayback_machine",
            PLAYWRIGHT="playwright",
            BEAUTIFULSOUP="beautifulsoup",
            REQUESTS_ONLY="requests_only",
        ),
    )

    result = await _agentic_discover_admin_state_blocks(
        states=["IN"],
        max_candidates_per_state=4,
        max_fetch_per_state=2,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert [
        statute["source_url"] for statute in result["state_blocks"][0]["statutes"]
    ] == [deep_url]