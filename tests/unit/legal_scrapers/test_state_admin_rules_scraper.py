from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_scrapers import legal_web_archive_search as legal_archive_module
from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as scraper_module
from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
    _agentic_discover_admin_state_blocks,
    _is_admin_rule_statute,
    _is_relaxed_recovery_text,
    _is_substantive_admin_statute,
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


@pytest.mark.anyio
async def test_agentic_discovery_seed_fetch_uses_initialized_max_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
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
                text="Official Alabama administrative rules body with authority and chapter text.",
                title="Alabama Administrative Code",
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(text="", title="", links=[])

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: ["https://admincode.legislature.state.al.us/administrative-code"])
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