from __future__ import annotations

import asyncio
import sys
import time
import types
from enum import Enum
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
    _candidate_massachusetts_cmr_urls_from_html,
    _candidate_montana_rule_urls_from_text,
    _candidate_utah_rule_urls_from_public_api,
    _discover_new_hampshire_archived_rule_document_urls,
    _discover_new_hampshire_archived_rule_document_urls_with_diagnostics,
    _is_admin_rule_statute,
    _is_direct_detail_candidate_url,
    _is_relaxed_recovery_text,
    _is_substantive_rule_text,
    _is_substantive_admin_statute,
    _normalize_admin_rule_payloads,
    _score_candidate_url,
    _wayback_iframe_replay_url,
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


def test_normalize_admin_rule_payloads_adds_trimmed_generic_aliases() -> None:
    scraped_rules = [
        {
            "state_code": "AZ",
            "state_name": "Arizona",
            "statutes": [
                {
                    "section_number": " A1 ",
                    "section_name": " TITLE 18. ENVIRONMENTAL QUALITY \n",
                    "source_url": "https://apps.azsos.gov/public_services/Title_18/18-04.rtf\n",
                    "full_text": " TITLE 18 text body\n",
                    "code_name": " Arizona Administrative Rules ",
                    "official_cite": " AZ Admin Rule A1 ",
                }
            ],
        }
    ]

    _normalize_admin_rule_payloads(scraped_rules)

    statute = scraped_rules[0]["statutes"][0]
    assert statute["section_number"] == "A1"
    assert statute["section_name"] == "TITLE 18. ENVIRONMENTAL QUALITY"
    assert statute["source_url"] == "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"
    assert statute["full_text"] == "TITLE 18 text body"
    assert statute["title"] == "TITLE 18. ENVIRONMENTAL QUALITY"
    assert statute["text"] == "TITLE 18 text body"
    assert statute["url"] == "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"
    assert statute["sourceUrl"] == "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"
    assert statute["sectionNumber"] == "A1"
    assert statute["sectionName"] == "TITLE 18. ENVIRONMENTAL QUALITY"
    assert statute["citation"] == "AZ Admin Rule A1"
    assert statute["codeName"] == "Arizona Administrative Rules"
    assert statute["description"] == "TITLE 18. ENVIRONMENTAL QUALITY"
    assert statute["structured_data"]["jsonld"]["sourceUrl"] == "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"


def test_curated_seeds_include_michigan_admin_rules_and_public_rhode_island_ricr() -> None:
    il_urls = scraper_module._extract_seed_urls_for_state("IL", "Illinois")
    mi_urls = scraper_module._extract_seed_urls_for_state("MI", "Michigan")
    ri_urls = scraper_module._extract_seed_urls_for_state("RI", "Rhode Island")
    ut_urls = scraper_module._extract_seed_urls_for_state("UT", "Utah")

    assert "https://www.ilga.gov/agencies/JCAR/AdminCode" in il_urls
    assert "https://www.ilga.gov/agencies/JCAR/EntirePart?titlepart=00100100" in il_urls
    assert "https://www.ilga.gov/commission/jcar/admincode/001/001001000A01000R.html" in il_urls
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
    ak_urls = scraper_module._extract_seed_urls_for_state("AK", "Alaska")
    ak_allowed_hosts = _allowed_discovery_hosts_for_state("AK", "Alaska")
    ut_urls = scraper_module._extract_seed_urls_for_state("UT", "Utah")
    az_allowed_hosts = _allowed_discovery_hosts_for_state("AZ", "Arizona")

    assert "https://azsos.gov/rules/arizona-administrative-code" in az_urls
    assert "https://apps.azsos.gov/public_services/CodeTOC.htm" in az_urls
    assert "https://apps.azsos.gov/public_services/Title_04/4-08.rtf" in az_urls
    assert "https://apps.azsos.gov/public_services/Title_06/6-11.rtf" in az_urls
    assert "https://apps.azsos.gov/public_services/Title_00.htm" not in az_urls
    assert all("legislature.az.gov" not in url.lower() for url in az_urls)
    assert all("www.azleg.gov" not in url.lower() for url in az_urls)
    assert "legislature.az.gov" not in az_allowed_hosts
    assert "www.azleg.gov" not in az_allowed_hosts

    assert "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules" in ut_urls
    assert "https://adminrules.utah.gov/public/home" not in ut_urls
    assert "https://adminrules.utah.gov/public/search" not in ut_urls

    assert "https://akrules.elaws.us/aac" in ak_urls
    assert all("legislature.ak.gov" not in url.lower() for url in ak_urls)
    assert all("legis.state.ak.us" not in url.lower() for url in ak_urls)
    assert "akrules.elaws.us" in ak_allowed_hosts
    assert "ltgov.alaska.gov" in ak_allowed_hosts
    assert "www.akleg.gov" in ak_allowed_hosts
    assert "legislature.ak.gov" not in ak_allowed_hosts
    assert "legis.state.ak.us" not in ak_allowed_hosts


def test_indiana_curated_seeds_focus_on_live_iar_hosts() -> None:
    in_urls = scraper_module._extract_seed_urls_for_state("IN", "Indiana")

    assert "https://iar.iga.in.gov/code/current" in in_urls
    assert "https://iar.iga.in.gov/code/2024" in in_urls
    assert "https://iar.iga.in.gov/code/current/10/1.5" in in_urls
    assert all("legislature.in.gov" not in url.lower() for url in in_urls)


def test_vermont_curated_seeds_drop_blocked_lexis_hosts() -> None:
    vt_urls = scraper_module._extract_seed_urls_for_state("VT", "Vermont")
    vt_allowed_hosts = _allowed_discovery_hosts_for_state("VT", "Vermont")

    assert "https://secure.vermont.gov/SOS/rules/" in vt_urls
    assert "https://secure.vermont.gov/SOS/rules/index.php" in vt_urls
    assert "https://sos.vermont.gov/secretary-of-state-services/apa-rules/" in vt_urls
    assert all("lexis" not in url.lower() for url in vt_urls)
    assert all("display.php?r=1049" not in url.lower() for url in vt_urls)
    assert "secure.vermont.gov" in vt_allowed_hosts
    assert "sos.vermont.gov" in vt_allowed_hosts
    assert "aoa.vermont.gov" in vt_allowed_hosts
    assert "www.lexisnexis.com" not in vt_allowed_hosts
    assert "advance.lexis.com" not in vt_allowed_hosts


def test_tennessee_curated_seeds_keep_service_pages_but_drop_dead_placeholders() -> None:
    tn_urls = scraper_module._extract_seed_urls_for_state("TN", "Tennessee")

    assert "https://publications.tnsosfiles.com/rules/" in tn_urls
    assert "https://sos.tn.gov/publications/services/administrative-register" in tn_urls
    assert "https://sos.tn.gov/publications/services/effective-rules-and-regulations-of-the-state-of-tennessee" in tn_urls
    assert "https://sharetngov.tnsosfiles.com/sos/rules/index.htm" in tn_urls
    assert "https://sharetngov.tnsosfiles.com/sos/rules/rules2.htm" in tn_urls
    assert "https://sharetngov.tnsosfiles.com/sos/pub/tar/index.htm" in tn_urls
    assert all("web.archive.org" not in url.lower() for url in tn_urls)
    assert all("www.tn.gov/sos/rules-and-regulations.html" not in url.lower() for url in tn_urls)
    assert all("legislature.tn.gov" not in url.lower() for url in tn_urls)
    assert all("capitol.tn.gov" not in url.lower() for url in tn_urls)


def test_curated_seeds_include_massachusetts_cmr_sources() -> None:
    ma_urls = scraper_module._extract_seed_urls_for_state("MA", "Massachusetts")
    ma_allowed_hosts = _allowed_discovery_hosts_for_state("MA", "Massachusetts")

    assert "https://www.sec.state.ma.us/divisions/pubs-regs/about-cmr.htm" in ma_urls
    assert "https://www.mass.gov/guides/code-of-massachusetts-regulations-cmr-by-number" in ma_urls
    assert "https://www.mass.gov/law-library/310-cmr" in ma_urls
    assert "https://www.mass.gov/regulations/310-CMR-100-adjudicatory-proceedings-0" in ma_urls
    assert "https://www.mass.gov/regulations/310-CMR-200-adopting-administrative-regulations" in ma_urls
    assert "https://www.mass.gov/regulations/310-CMR-700-air-pollution-control-0" in ma_urls
    assert "www.mass.gov" in ma_allowed_hosts
    assert "www.sec.state.ma.us" in ma_allowed_hosts


def test_california_admin_seed_urls_exclude_leginfo_templates_and_hosts() -> None:
    ca_urls = scraper_module._extract_seed_urls_for_state("CA", "California")
    allowed_hosts = _allowed_discovery_hosts_for_state("CA", "California")

    assert "https://govt.westlaw.com/calregs/Index" in ca_urls
    assert "https://oal.ca.gov/publications/ccr/" in ca_urls
    assert "https://oal.ca.gov/publications/" in ca_urls
    assert all("leginfo.legislature.ca.gov" not in url.lower() for url in ca_urls)
    assert "govt.westlaw.com" in allowed_hosts
    assert "oal.ca.gov" in allowed_hosts
    assert "leginfo.legislature.ca.gov" not in allowed_hosts


def test_wyoming_admin_seed_urls_exclude_dead_legislature_hosts() -> None:
    wy_urls = scraper_module._extract_seed_urls_for_state("WY", "Wyoming")
    allowed_hosts = _allowed_discovery_hosts_for_state("WY", "Wyoming")

    assert "https://rules.wyo.gov/Search.aspx?mode=7" in wy_urls
    assert all(not url.rstrip("/").endswith("rules.wyo.gov") for url in wy_urls)
    assert all(
        not (url.lower().endswith("rules.wyo.gov/search.aspx") and "mode=7" not in url.lower())
        for url in wy_urls
    )
    assert all("wyoleg.gov" not in url.lower() for url in wy_urls)
    assert all("legislature.wy.gov" not in url.lower() for url in wy_urls)
    assert "rules.wyo.gov" in allowed_hosts
    assert "wyoleg.gov" not in allowed_hosts
    assert "www.wyoleg.gov" not in allowed_hosts
    assert "legislature.wy.gov" not in allowed_hosts


def test_arkansas_admin_seed_urls_exclude_dead_legislature_hosts() -> None:
    ar_urls = scraper_module._extract_seed_urls_for_state("AR", "Arkansas")
    allowed_hosts = _allowed_discovery_hosts_for_state("AR", "Arkansas")

    assert "https://codeofarrules.arkansas.gov/" in ar_urls
    assert "https://sos-rules-reg.ark.org/" in ar_urls
    assert "https://www.sos.arkansas.gov/rules-regulations/" in ar_urls
    assert all("legislature.ar.gov" not in url.lower() for url in ar_urls)
    assert all("arkleg.state.ar.us" not in url.lower() for url in ar_urls)
    assert "codeofarrules.arkansas.gov" in allowed_hosts
    assert "sos-rules-reg.ark.org" in allowed_hosts
    assert "legislature.ar.gov" not in allowed_hosts
    assert "arkleg.state.ar.us" not in allowed_hosts


def test_candidate_links_from_html_keeps_california_official_ccr_host_when_allowed() -> None:
    html = """
    <html>
      <body>
        <a href="https://govt.westlaw.com/calregs/Index?transitionType=Default&amp;contextData=%28sc.Default%29">California Code of Regulations</a>
      </body>
    </html>
    """

    links = _candidate_links_from_html(
        html,
        base_host="oal.ca.gov",
        page_url="https://oal.ca.gov/publications/ccr/",
        limit=4,
        allowed_hosts=_allowed_discovery_hosts_for_state("CA", "California"),
    )

    assert any(link.startswith("https://govt.westlaw.com/calregs/Index") for link in links)


def test_candidate_links_from_html_keeps_california_westlaw_document_link() -> None:
        html = """
        <html>
            <body>
                <a href="/calregs/Document/I7A6B47D0FD4311ECBA0CE8BD2C3F45C2?viewType=FullText&amp;originationContext=documenttoc&amp;transitionType=CategoryPageItem&amp;contextData=(sc.Default)">&#167; 1. Chapter Definitions.</a>
            </body>
        </html>
        """

        links = _candidate_links_from_html(
                html,
                base_host="govt.westlaw.com",
                page_url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=I7DA20CB04C6611EC93A8000D3A7C4BC3&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)",
                limit=4,
                allowed_hosts=_allowed_discovery_hosts_for_state("CA", "California"),
        )

        assert links == [
                "https://govt.westlaw.com/calregs/Document/I7A6B47D0FD4311ECBA0CE8BD2C3F45C2?viewType=FullText&originationContext=documenttoc&transitionType=CategoryPageItem&contextData=(sc.Default)",
        ]


def test_gap_summary_host_key_collapses_california_portal_hosts_into_official_ccr_host() -> None:
    assert scraper_module._gap_summary_host_key("https://oal.ca.gov/publications/ccr/") == "govt.westlaw.com"
    assert scraper_module._gap_summary_host_key("http://carules.elaws.us/search/allcode") == "govt.westlaw.com"
    assert scraper_module._gap_summary_host_key("https://govt.westlaw.com/calregs/Index") == "govt.westlaw.com"


def test_gap_summary_host_key_collapses_utah_admin_rule_host_family() -> None:
    assert scraper_module._gap_summary_host_key("https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules") == "adminrules.utah.gov"
    assert scraper_module._gap_summary_host_key("https://rules.utah.gov/publications/code-updates/") == "adminrules.utah.gov"
    assert scraper_module._gap_summary_host_key("https://le.utah.gov/xcode/Title63G/Chapter3/63G-3.html") == "adminrules.utah.gov"
    assert scraper_module._gap_summary_host_key("https://legislature.ut.gov") == "adminrules.utah.gov"


def test_gap_summary_host_key_collapses_rhode_island_admin_rule_host_family() -> None:
    assert scraper_module._gap_summary_host_key("https://rules.sos.ri.gov/regulations/part/510-00-00-4") == "rules.sos.ri.gov"
    assert scraper_module._gap_summary_host_key("https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations") == "rules.sos.ri.gov"
    assert scraper_module._gap_summary_host_key("https://sos.ri.gov/open-government-center") == "rules.sos.ri.gov"
    assert scraper_module._gap_summary_host_key("https://legislature.ri.gov/ricr") == "rules.sos.ri.gov"
    assert scraper_module._gap_summary_host_key("http://webserver.rilin.state.ri.us/Statutes/TITLE6/INDEX.HTM") == "rules.sos.ri.gov"


def test_gap_summary_host_key_collapses_massachusetts_admin_rule_host_family() -> None:
    assert scraper_module._gap_summary_host_key("https://www.mass.gov/regulations/310-CMR-700-air-pollution-control-0") == "mass.gov"
    assert scraper_module._gap_summary_host_key("https://www.sec.state.ma.us/divisions/pubs-regs/about-cmr.htm") == "mass.gov"
    assert scraper_module._gap_summary_host_key("https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXVI/Chapter111/Section142A") == "mass.gov"
    assert scraper_module._gap_summary_host_key("https://legislature.ma.gov/") == "mass.gov"


def test_is_direct_detail_candidate_url_recognizes_indiana_rule_detail_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url("https://iar.iga.in.gov/code/current/10/1.5") is True
    assert scraper_module._is_direct_detail_candidate_url("https://iar.iga.in.gov/code/2006/25/7") is True
    assert scraper_module._is_direct_detail_candidate_url("https://iar.iga.in.gov/code/current") is False


def test_is_direct_detail_candidate_url_recognizes_alabama_admin_code_detail_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code"
    ) is False
    assert scraper_module._is_direct_detail_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code#A"
    ) is False
    assert scraper_module._is_direct_detail_candidate_url(
        "https://admincode.legislature.state.al.us/agency"
    ) is False
    assert scraper_module._is_immediate_direct_detail_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01"
    ) is True
    assert scraper_module._is_immediate_direct_detail_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code"
    ) is False


def test_is_direct_detail_candidate_url_recognizes_new_hampshire_archived_rule_chapters() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr100.html"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr.html"
    ) is False
    assert scraper_module._is_direct_detail_candidate_url(
        "https://www.gencourt.state.nh.us/rules/state_agencies/env-ws1101-1105.html"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx"
    ) is False


def test_new_hampshire_admin_seed_urls_exclude_live_root_pages() -> None:
    nh_urls = scraper_module._extract_seed_urls_for_state("NH", "New Hampshire")
    allowed_hosts = _allowed_discovery_hosts_for_state("NH", "New Hampshire")

    assert "https://web.archive.org/web/20250129103908/https://gc.nh.gov/rules/about_rules/listagencies.aspx" in nh_urls
    assert "https://web.archive.org/web/20250207090111/https://gc.nh.gov/rules/about_rules/listagencies.aspx" in nh_urls
    assert "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr100.html" in nh_urls
    assert "https://gencourt.state.nh.us/rules/state_agencies/env-ws1101-1105.html" in nh_urls
    assert "https://gc.nh.gov/rules/state_agencies/" not in nh_urls
    assert "https://gc.nh.gov/rules/" not in nh_urls
    assert "https://www.gencourt.state.nh.us/rules/state_agencies/" not in nh_urls
    assert "https://www.gencourt.state.nh.us/rules/" not in nh_urls
    assert "web.archive.org" in allowed_hosts
    assert "gencourt.state.nh.us" in allowed_hosts


def test_new_hampshire_archived_rules_root_is_inventory_page() -> None:
    text = (
        "Office of Legislative Services Administrative Rules QUICK LINKS Rulemaking Search JLCAR Meeting Dates Rules by Agency "
        "CONTACT Administrative Rules office can provide information about rules and RSA 541-A but cannot give legal advice. "
        "WELCOME The Office of Legislative Services, Administrative Rules is the New Hampshire state government office where all proposed and adopted administrative rules must be filed. "
        "NEWS Emergency Rules Currently in Effect Effective Adopted Rules as Filed The General Court of New Hampshire"
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Administrative Rules",
        url="https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/",
    ) is True
    assert _is_substantive_rule_text(
        text=text,
        title="Administrative Rules",
        url="https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/",
        min_chars=160,
    ) is False


def test_new_hampshire_archived_agency_toc_is_inventory_page() -> None:
    text = (
        "TABLE OF CONTENTS CHAPTER Agr 100 ORGANIZATIONAL RULES PART Agr 101 PURPOSE "
        "CHAPTER Agr 200 AGRICULTURAL COMMODITIES CHAPTER Agr 300 ANIMAL INDUSTRY "
        "CHAPTER Agr 400 PEST CONTROL AND PLANT INDUSTRY"
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="TABLE OF CONTENTS",
        url="https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr.html",
    ) is True
    assert _is_substantive_rule_text(
        text=text,
        title="TABLE OF CONTENTS",
        url="https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr.html",
        min_chars=160,
    ) is False


def test_wayback_iframe_replay_url_transforms_html_replay_pages() -> None:
    assert _wayback_iframe_replay_url(
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    ) == "https://web.archive.org/web/20250308091642if_/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    assert _wayback_iframe_replay_url(
        "https://web.archive.org/web/20250308091642if_/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    ) == "https://web.archive.org/web/20250308091642if_/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    assert scraper_module._wayback_replay_timestamp(
        "https://web.archive.org/web/20250308091642if_/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    ) == "20250308091642"


@pytest.mark.asyncio
async def test_scrape_new_hampshire_archived_rule_detail_uses_exact_wayback_capture_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archived_url = "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    async def _fake_get_wayback_content(url: str, timestamp: str, closest: bool = True):
        assert url == "https://gc.nh.gov/rules/state_agencies/he-p300.html"
        assert timestamp == "20250308091642"
        return {
            "status": "success",
            "content": b"<html><head><title>He-P 300</title></head><body><p>Chapter He-P 300 Communicable Diseases</p><p>Statutory Authority: RSA 141-C.</p></body></html>",
            "wayback_url": archived_url,
            "capture_timestamp": timestamp,
        }

    monkeypatch.setattr(wayback_machine_engine, "get_wayback_content", _fake_get_wayback_content)
    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct requests should not be used")))
    monkeypatch.setattr(scraper_module, "_fetch_html_bypassing_challenge", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fallback fetch should not be used")))

    scraped = await scraper_module._scrape_new_hampshire_archived_rule_detail(archived_url)

    assert scraped is not None
    assert scraped.extraction_provenance["source"] == "wayback_engine"
    assert scraped.extraction_provenance["capture_timestamp"] == "20250308091642"
    assert "Statutory Authority" in scraped.text


@pytest.mark.asyncio
async def test_scrape_new_hampshire_archived_rule_detail_prefers_archived_wayback_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archived_url = "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    observed_urls: list[str] = []
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    async def _fake_fetch_html_bypassing_challenge(url: str):
        observed_urls.append(url)
        return {
            "text": "Chapter He-P 300 Communicable Diseases Statutory Authority: RSA 141-C. Source. #6039, eff 7-1-95.",
            "html": "<html><head><title>He-P 300</title></head><body><p>Chapter He-P 300 Communicable Diseases</p></body></html>",
            "source": "wayback_machine",
        }

    monkeypatch.setattr(wayback_machine_engine, "get_wayback_content", lambda *args, **kwargs: {"status": "error"})
    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct requests should not be used")))
    monkeypatch.setattr(scraper_module, "_fetch_html_bypassing_challenge", _fake_fetch_html_bypassing_challenge)

    scraped = await scraper_module._scrape_new_hampshire_archived_rule_detail(archived_url)

    assert observed_urls == [archived_url]
    assert scraped is not None
    assert scraped.url == archived_url
    assert scraped.method_used == "new_hampshire_wayback_replay"
    assert scraped.extraction_provenance["fetch_url"] == archived_url
    assert "Statutory Authority" in scraped.text


@pytest.mark.asyncio
async def test_scrape_new_hampshire_archived_rule_detail_skips_wayback_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archived_url = "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html"
    original_url = "https://gc.nh.gov/rules/state_agencies/he-p300.html"
    observed_urls: list[str] = []
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    async def _fake_fetch_html_bypassing_challenge(url: str):
        observed_urls.append(url)
        if url == archived_url:
            return {
                "text": "Wayback Machine Ask the publishers to restore access to 500,000+ books. Internet Archive logo.",
                "html": "<html><head><title>Wayback Machine</title></head><body>Ask the publishers Internet Archive</body></html>",
                "source": "common_crawl",
            }
        if url == original_url:
            return {
                "text": "Chapter He-P 300 Communicable Diseases Statutory Authority: RSA 141-C. Source. #6039, eff 7-1-95.",
                "html": "<html><head><title>He-P 300</title></head><body><p>Chapter He-P 300 Communicable Diseases</p></body></html>",
                "source": "wayback_machine",
            }
        return None

    monkeypatch.setattr(wayback_machine_engine, "get_wayback_content", lambda *args, **kwargs: {"status": "error"})
    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct requests should not be used")))
    monkeypatch.setattr(scraper_module, "_fetch_html_bypassing_challenge", _fake_fetch_html_bypassing_challenge)

    scraped = await scraper_module._scrape_new_hampshire_archived_rule_detail(archived_url)

    assert observed_urls == [archived_url, original_url]
    assert scraped is not None
    assert scraped.extraction_provenance["fetch_url"] == original_url
    assert "Statutory Authority" in scraped.text


@pytest.mark.asyncio
async def test_scrape_new_hampshire_archived_rule_detail_skips_blocked_403_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archived_url = "https://web.archive.org/web/20250129103908/https://gc.nh.gov/rules/state_agencies/stra1100.html"
    original_url = "https://gc.nh.gov/rules/state_agencies/stra1100.html"
    observed_urls: list[str] = []
    from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine

    async def _fake_fetch_html_bypassing_challenge(url: str):
        observed_urls.append(url)
        if url == archived_url:
            return {
                "text": "Error 403 Web Page Blocked block URL: www.gc.nh.gov/robots.txt Attack ID: 20000051 Message ID: 000402357687",
                "html": "<html><head><title>Error 403</title></head><body><h1>Error 403</h1><p>Web Page Blocked</p><p>URL: www.gc.nh.gov/robots.txt</p></body></html>",
                "source": "common_crawl",
            }
        if url == original_url:
            return {
                "text": "Chapter Stra 1100 Hearings Statutory Authority: RSA 541-A. Source. #1234, eff 1-1-24.",
                "html": "<html><head><title>Stra 1100</title></head><body><p>Chapter Stra 1100 Hearings</p><p>Statutory Authority: RSA 541-A.</p></body></html>",
                "source": "wayback_machine",
            }
        return None

    monkeypatch.setattr(wayback_machine_engine, "get_wayback_content", lambda *args, **kwargs: {"status": "error"})
    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct requests should not be used")))
    monkeypatch.setattr(scraper_module, "_fetch_html_bypassing_challenge", _fake_fetch_html_bypassing_challenge)

    scraped = await scraper_module._scrape_new_hampshire_archived_rule_detail(archived_url)

    assert observed_urls == [archived_url, original_url]
    assert scraped is not None
    assert scraped.extraction_provenance["fetch_url"] == original_url
    assert "Statutory Authority" in scraped.text


def test_new_hampshire_archived_checkrule_page_is_not_substantive_rule_text() -> None:
    text = (
        "Administrative Rules HOW TO DOUBLE-CHECK THE ONLINE RULE CAUTION ALWAYS DOUBLE-CHECK ANY ONLINE RULE. "
        "CHECKING FOR LATER FILINGS NOT YET ONLINE CHECKING FOR EXPIRATION Official Version of a Rule "
        "Administrative Rules office can provide information about rules and RSA 541-A but cannot give legal advice."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="How To Double-Check the Online Rule",
        url="https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/checkrule.aspx",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="How To Double-Check the Online Rule",
        url="https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/checkrule.aspx",
    ) is False


def test_new_hampshire_archived_blocked_403_page_is_not_substantive_rule_text() -> None:
    text = (
        "Error 403 Web Page Blocked block URL: www.gc.nh.gov/robots.txt Client IP: 18.97.14.91 "
        "Attack ID: 20000051 Message ID: 000402357687 What happened? The page cannot be displayed."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Error 403",
        url="https://web.archive.org/web/20250129103908/https://gc.nh.gov/rules/state_agencies/stra1100.html",
        min_chars=160,
    ) is False


@pytest.mark.anyio
async def test_discover_new_hampshire_archived_rule_document_urls_from_listagencies(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx"
    listagencies_html = """
    <html>
      <body>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr.html">Agr</a>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/env-wq300.html">Env-Wq 300</a>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/about_rules/checkrule.aspx">Check Rule</a>
      </body>
    </html>
    """
    agr_toc_html = """
    <html>
      <body>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr100.html">Agr 100</a>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr200.html">Agr 200</a>
      </body>
    </html>
    """

    class _FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, *args, **kwargs):
        if url in {
            seed_url,
            scraper_module._wayback_iframe_replay_url(seed_url),
        }:
            return _FakeResponse(listagencies_html)
        agr_url = "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr.html"
        if url in {
            agr_url,
            scraper_module._wayback_iframe_replay_url(agr_url),
        }:
            return _FakeResponse(agr_toc_html)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(scraper_module.requests, "get", _fake_get)

    urls = await _discover_new_hampshire_archived_rule_document_urls(
        seed_urls=[seed_url],
        allowed_hosts=_allowed_discovery_hosts_for_state("NH", "New Hampshire"),
        limit=4,
    )

    assert urls == [
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/env-wq300.html",
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr100.html",
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr200.html",
    ]


@pytest.mark.asyncio
async def test_discover_new_hampshire_archived_rule_document_urls_with_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx"
    listagencies_html = """
    <html>
      <body>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr.html">Agr</a>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/env-wq300.html">Env-Wq 300</a>
      </body>
    </html>
    """
    agr_toc_html = """
    <html>
      <body>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr100.html">Agr 100</a>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr200.html">Agr 200</a>
      </body>
    </html>
    """

    class _FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, *args, **kwargs):
        if url in {
            seed_url,
            scraper_module._wayback_iframe_replay_url(seed_url),
        }:
            return _FakeResponse(listagencies_html)
        agr_url = "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr.html"
        if url in {
            agr_url,
            scraper_module._wayback_iframe_replay_url(agr_url),
        }:
            return _FakeResponse(agr_toc_html)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(scraper_module.requests, "get", _fake_get)

    result = await _discover_new_hampshire_archived_rule_document_urls_with_diagnostics(
        seed_urls=[seed_url],
        allowed_hosts=_allowed_discovery_hosts_for_state("NH", "New Hampshire"),
        limit=4,
    )

    assert result["document_urls"] == [
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/env-wq300.html",
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr100.html",
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/agr200.html",
    ]
    assert result["diagnostics"] == {
        "frontier_count": 1,
        "pages_attempted": 2,
        "pages_fetched": 2,
        "fetch_attempts": 2,
        "fetch_failures": 0,
        "shell_pages_rejected": 0,
        "capture_candidates_discovered": 0,
        "inventory_pages_enqueued": 1,
        "links_considered": 4,
        "document_urls_found": 3,
    }


@pytest.mark.asyncio
async def test_discover_new_hampshire_archived_rule_document_urls_recovers_via_cdx_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx"
    recovered_seed_url = "https://web.archive.org/web/20250129103908/https://gc.nh.gov/rules/about_rules/listagencies.aspx"
    recovered_agr_url = "https://web.archive.org/web/20250211224211/https://gc.nh.gov/rules/state_agencies/agr.html"
    shell_html = """
    <html><head><title>Wayback Machine</title></head><body>Wayback Machine Internet Archive Ask the publishers</body></html>
    """
    listagencies_html = """
    <html>
      <body>
        <a href="/web/20250211224211/https://gc.nh.gov/rules/state_agencies/agr.html">Agr</a>
        <a href="/web/20250307175245/https://gc.nh.gov/rules/state_agencies/env-wq300.html">Env-Wq 300</a>
      </body>
    </html>
    """
    agr_toc_html = """
    <html>
      <body>
        <a href="https://web.archive.org/web/20250211224211/http://www.gencourt.state.nh.us/rules/state_agencies/agr100.html">Agr 100</a>
        <a href="https://web.archive.org/web/20250211224211/http://www.gencourt.state.nh.us/rules/state_agencies/agr200.html">Agr 200</a>
      </body>
    </html>
    """

    class _FakeResponse:
        def __init__(self, text: str, *, json_payload=None):
            self.text = text
            self._json_payload = json_payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            if self._json_payload is None:
                raise AssertionError("unexpected json() call")
            return self._json_payload

    def _fake_get(url: str, *args, **kwargs):
        params = kwargs.get("params") or {}
        if url == "https://web.archive.org/cdx/search/cdx":
            if params.get("url") == "https://gc.nh.gov/rules/about_rules/listagencies.aspx":
                return _FakeResponse(
                    "",
                    json_payload=[
                        ["timestamp", "original", "statuscode", "mimetype"],
                        ["20250129103908", "https://gc.nh.gov/rules/about_rules/listagencies.aspx", "200", "text/html"],
                    ],
                )
            if params.get("url") == "https://gc.nh.gov/rules/state_agencies/agr.html":
                return _FakeResponse(
                    "",
                    json_payload=[
                        ["timestamp", "original", "statuscode", "mimetype"],
                        ["20250211224211", "https://gc.nh.gov/rules/state_agencies/agr.html", "200", "text/html"],
                    ],
                )
            raise AssertionError(f"unexpected CDX params: {params}")
        if url in {
            seed_url,
            scraper_module._wayback_iframe_replay_url(seed_url),
        }:
            return _FakeResponse(shell_html)
        if url in {
            recovered_seed_url,
            scraper_module._wayback_iframe_replay_url(recovered_seed_url),
        }:
            return _FakeResponse(listagencies_html)
        if url in {
            recovered_agr_url,
            scraper_module._wayback_iframe_replay_url(recovered_agr_url),
        }:
            return _FakeResponse(agr_toc_html)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(scraper_module.requests, "get", _fake_get)

    result = await _discover_new_hampshire_archived_rule_document_urls_with_diagnostics(
        seed_urls=[seed_url],
        allowed_hosts=_allowed_discovery_hosts_for_state("NH", "New Hampshire"),
        limit=4,
    )

    assert result["document_urls"] == [
        "https://web.archive.org/web/20250307175245/https://gc.nh.gov/rules/state_agencies/env-wq300.html",
        "https://web.archive.org/web/20250211224211/http://www.gencourt.state.nh.us/rules/state_agencies/agr100.html",
        "https://web.archive.org/web/20250211224211/http://www.gencourt.state.nh.us/rules/state_agencies/agr200.html",
    ]
    assert result["diagnostics"]["shell_pages_rejected"] >= 1
    assert result["diagnostics"]["capture_candidates_discovered"] >= 1
    assert result["diagnostics"]["pages_fetched"] == 2


def test_is_direct_detail_candidate_url_recognizes_vermont_rule_display_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://advance.lexis.com/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00008-00"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://secure.vermont.gov/SOS/rules/display.php?r=1049"
    ) is False
    assert scraper_module._is_direct_detail_candidate_url(
        "https://secure.vermont.gov/SOS/rules/search.php"
    ) is False


def test_is_direct_detail_candidate_url_recognizes_tennessee_sharetngov_rule_chapters() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/0020/0020.htm"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/0020/0020-01.20170126.pdf"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/1200/1200-13/1200-13-14.20150930.pdf"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/rules2.htm"
    ) is False


def test_is_direct_detail_candidate_url_recognizes_wyoming_ajax_rule_viewer() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules&PROGRAM_ID=347&MODE=7"
    ) is False


def test_is_direct_detail_candidate_url_recognizes_texas_appian_rule_summary_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://texas-sos.appianportalsgov.com/rules-and-meetings?recordId=204859&queryAsDate=03/14/2026&interface=VIEW_TAC_SUMMARY&$locale=en_US"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC&title=1&part=1"
    ) is False


def test_is_direct_detail_candidate_url_recognizes_oklahoma_rules_api_section_urls() -> None:
    assert scraper_module._is_direct_detail_candidate_url("https://rules.ok.gov/code?titleNum=10") is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://rules.ok.gov/code?titleNum=10&sectionNum=10%3A1-1-1"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url("https://rules.ok.gov/code") is False


def test_is_direct_detail_candidate_url_recognizes_arkansas_code_rule_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=1"
    ) is False
    assert scraper_module._is_direct_detail_candidate_url(
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=section&titleID=2&chapterID=269&subChapterID=335&partID=1307&subPartID=8275&sectionID=54466"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://codeofarrules.arkansas.gov/Rules/Search"
    ) is False


def test_is_direct_detail_candidate_url_recognizes_alaska_aac_section_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url("https://akrules.elaws.us/aac/1.05.010") is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://www.akleg.gov/basis/aac.asp?media=print&secStart=1.05.010&secEnd=1.05.010"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url("https://akrules.elaws.us/aac/1") is False
    assert scraper_module._is_direct_detail_candidate_url("https://akrules.elaws.us/aac/1.05") is False


def test_is_direct_detail_candidate_url_recognizes_georgia_gac_rule_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url("https://rules.sos.ga.gov/gac/120-2-1-.01") is True
    assert scraper_module._is_direct_detail_candidate_url("https://rules.sos.ga.gov/gac/120-2") is False
    assert scraper_module._is_direct_detail_candidate_url("https://rules.sos.ga.gov/gac/120-2-1") is False


def test_is_direct_detail_candidate_url_recognizes_south_dakota_rule_pages() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://sdlegislature.gov/Rules/Administrative/01:15"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx?Rule=20:48:03:01"
    ) is True
    assert scraper_module._is_direct_detail_candidate_url(
        "https://sdlegislature.gov/Rules/Administrative"
    ) is False


def test_tennessee_sharetngov_rule_hubs_are_inventory_pages() -> None:
    text = (
        "Tennessee Department of State: Publications Administrative Register Rules & Regulations "
        "Effective Rules View All Effective Rule Chapters View Effective Rules by Month Archived Rule Filings"
    )

    assert scraper_module._looks_like_official_rule_index_page(
        text=text,
        title="Tennessee Department of State: Publications",
        url="https://sharetngov.tnsosfiles.com/sos/rules/index.htm",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Tennessee Department of State: Publications",
        url="https://sharetngov.tnsosfiles.com/sos/rules/rules2.htm",
    ) is True


def test_tennessee_tenncare_rules_page_is_inventory_page() -> None:
    text = (
        "Tennessee Department of State: Publications TennCare Rules Effective Rules Pending Rules Rulemaking Hearings "
        "Archived Rule Filings TennCare Rules Filing Rule Filing Rule"
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Tennessee Department of State: Publications",
        url="https://sharetngov.tnsosfiles.com/sos/rules/tenncare.htm",
    ) is True


def test_tennessee_sharetngov_rule_chapter_toc_pages_are_inventory_pages() -> None:
    text = (
        "Rules of the Tennessee State Board of Accountancy Click on the rule you want to view or print. "
        "Keywords may be searched for in individual PDF files by using the Find button. "
        "Chapter Description Introduction Table of Contents and Administrative History 0020-01 Board of Accountancy"
    )
    nested_text = (
        "Rules of the Tennessee Department of Health Click on the rule you want to view or print. "
        "Keywords may be searched for in individual PDF files by using the Find button. "
        "Chapter Description 1200-13-01 TennCare 1200-13-02 Eligibility"
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="0020 - Tennessee State Board of Accountancy Rules",
        url="https://sharetngov.tnsosfiles.com/sos/rules/0020/0020.htm",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=nested_text,
        title="1200-13 Tennessee Rules and Regulations",
        url="https://sharetngov.tnsosfiles.com/sos/rules/1200/1200-13/1200-13.htm",
    ) is True


def test_alaska_rule_inventory_detection_distinguishes_index_chapter_and_section_pages() -> None:
    ltgov_text = (
        "Regulations Proposed Regulations Adopted Regulations Alaska Administrative Code "
        "Department of Law "
    )
    aac_index_text = " ".join(
        ["Alaska Administrative Code"]
        + [f"Title {index}. Sample title" for index in range(1, 10)]
    )
    aac_title_text = (
        "Alaska Administrative Code Title 1. General Provisions "
        "Chapter 1.05. Procedures Chapter 1.10. Licensing"
    )
    aac_chapter_text = (
        "Alaska Administrative Code Chapter 1.05. Procedures "
        "Section 1.05.010. Purpose Section 1.05.020. Scope Section 1.05.030. Filing"
    )
    aac_section_text = (
        "Alaska Administrative Code 1 AAC 1.05.010. Purpose Authority: AS 44.62.020 History: Eff. 1/1/2024"
    )
    akleg_text = " ".join(
        ["Alaska Administrative Code", "This page is no longer used please use www.akleg.gov"]
        + [f"Title {index}. Legacy title" for index in range(1, 10)]
    )

    assert scraper_module._looks_like_non_rule_admin_page(
        text=ltgov_text,
        title="Regulations",
        url="https://ltgov.alaska.gov/information/regulations/",
    ) is True
    assert scraper_module._looks_like_official_rule_index_page(
        text=aac_index_text,
        title="Alaska Administrative Code",
        url="https://akrules.elaws.us/aac",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=aac_title_text,
        title="Alaska Administrative Code",
        url="https://akrules.elaws.us/aac/1",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=aac_chapter_text,
        title="Alaska Administrative Code",
        url="https://akrules.elaws.us/aac/1.05",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=aac_section_text,
        title="1 AAC 1.05.010",
        url="https://akrules.elaws.us/aac/1.05.010",
    ) is False
    assert scraper_module._looks_like_rule_inventory_page(
        text=akleg_text,
        title="Alaska Administrative Code",
        url="https://www.akleg.gov/basis/aac.asp",
    ) is True


def test_alaska_candidate_url_scoring_prefers_section_detail_over_indexes() -> None:
    ltgov_score = _score_candidate_url("https://ltgov.alaska.gov/information/regulations/")
    index_score = _score_candidate_url("https://akrules.elaws.us/aac")
    title_score = _score_candidate_url("https://akrules.elaws.us/aac/1")
    chapter_score = _score_candidate_url("https://akrules.elaws.us/aac/1.05")
    section_score = _score_candidate_url("https://akrules.elaws.us/aac/1.05.010")
    akleg_print_score = _score_candidate_url(
        "https://www.akleg.gov/basis/aac.asp?media=print&secStart=1.05.010&secEnd=1.05.010"
    )
    bookview_score = _score_candidate_url("https://akrules.elaws.us/bookview/1.05")

    assert ltgov_score > 0
    assert index_score > ltgov_score
    assert title_score > index_score
    assert chapter_score > title_score
    assert section_score > chapter_score
    assert akleg_print_score >= section_score
    assert bookview_score < chapter_score


def test_georgia_rule_inventory_detection_distinguishes_gac_index_chapter_subject_and_rule_pages() -> None:
    gac_index_text = " ".join(
        ["GA R&R", "Home Browse Help"]
        + [f"Department {index}. Sample agency" for index in range(20, 30)]
    )
    gac_department_text = (
        "GA R&R Department 120. OFFICE OF COMMISSIONER OF INSURANCE "
        "Chapter 120-1. General Rules Chapter 120-2. Rules of Commissioner of Insurance "
        "Subject 120-2-1. Organization Subject 120-2-2. Practice and Procedure "
        "Subject 120-2-3. Licensing"
    )
    gac_chapter_text = (
        "GA R&R Chapter 120-2. RULES OF COMMISSIONER OF INSURANCE "
        "Subject 120-2-1. Organization Subject 120-2-2. Practice and Procedure "
        "Subject 120-2-3. Licensing Subject 120-2-4. Enforcement"
    )
    gac_subject_text = (
        "GA R&R Subject 120-2-1 ORGANIZATION "
        "Rule 120-2-1-.01 The Commissioner of Insurance "
        "Rule 120-2-1-.02 Agents Licensing Section "
        "Rule 120-2-1-.03 Consumer Services Section"
    )
    gac_rule_text = (
        "Ga. Comp. R. & Regs. r. 120-2-1-.01 The Commissioner of Insurance Georgia Administrative Code "
        "Department 120. OFFICE OF COMMISSIONER OF INSURANCE Chapter 120-2. RULES OF COMMISSIONER OF INSURANCE "
        "Subject 120-2-1. ORGANIZATION Current through Rules and Regulations filed through February 19, 2026 "
        "The Commissioner of Insurance of the State of Georgia is charged with the administration and enforcement of the Georgia Insurance Code."
    )

    assert scraper_module._looks_like_official_rule_index_page(
        text=gac_index_text,
        title="GA R&R - GAC",
        url="https://rules.sos.ga.gov/gac",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=gac_department_text,
        title="GA R&R - Department 120",
        url="https://rules.sos.ga.gov/gac/120",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=gac_chapter_text,
        title="GA R&R - GAC - Chapter 120-2. RULES OF COMMISSIONER OF INSURANCE",
        url="https://rules.sos.ga.gov/gac/120-2",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=gac_subject_text,
        title="GA R&R - GAC - Subject 120-2-1 ORGANIZATION",
        url="https://rules.sos.ga.gov/gac/120-2-1",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=gac_rule_text,
        title="GA R&R - GAC - Rule 120-2-1-.01. The Commissioner of Insurance",
        url="https://rules.sos.ga.gov/gac/120-2-1-.01",
    ) is False


def test_georgia_candidate_url_scoring_prefers_rule_over_subject_and_chapter() -> None:
    root_score = _score_candidate_url("https://rules.sos.ga.gov/gac")
    department_score = _score_candidate_url("https://rules.sos.ga.gov/gac/120")
    chapter_score = _score_candidate_url("https://rules.sos.ga.gov/gac/120-2")
    subject_score = _score_candidate_url("https://rules.sos.ga.gov/gac/120-2-1")
    rule_score = _score_candidate_url("https://rules.sos.ga.gov/gac/120-2-1-.01")
    legislature_score = _score_candidate_url("http://www.legis.ga.gov/regulations")

    assert department_score > root_score
    assert chapter_score > department_score
    assert subject_score > chapter_score
    assert rule_score > subject_score
    assert legislature_score < root_score


def test_new_mexico_rule_inventory_detection_distinguishes_explanation_titles_title_and_chapter_pages() -> None:
    explanation_text = (
        "Explanation of the New Mexico Administrative Code What Are State Rules? "
        "History of the Code Structure of the NMAC Anatomy of a Rule Related Pages "
        "Powered by Real Time Solutions"
    )
    titles_text = " ".join(
        ["New Mexico Administrative Code", "NMAC Titles", "Expand List"]
        + [f"Title {index} - Sample subject" for index in range(1, 11)]
    )
    title_text = (
        "Title 07 - Health New Mexico Administrative Code Expand List "
        "Chapter 1 7.1.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 2 7.2.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 3 7.3.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 4 7.4.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 5 7.5.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 6 7.6.1 NMAC GENERAL PROVISIONS [RESERVED] "
    )
    chapter_text = (
        "Title 07 - Health New Mexico Administrative Code Expand List "
        "Chapter 25 7.25.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 26 7.26.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 28 7.28.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 29 7.29.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 30 7.30.1 NMAC GENERAL PROVISIONS [RESERVED] "
        "Chapter 31 7.31.1 NMAC GENERAL PROVISIONS [RESERVED] "
    )

    assert scraper_module._looks_like_non_rule_admin_page(
        text=explanation_text,
        title="Explanation of the New Mexico Administrative Code - State Records Center & Archives",
        url="https://www.srca.nm.gov/nmac-home/explanation-of-the-new-mexico-administrative-code/",
    ) is True
    assert scraper_module._looks_like_official_rule_index_page(
        text=titles_text,
        title="New Mexico Administrative Code Titles - State Records Center & Archives",
        url="https://www.srca.nm.gov/nmac-home/nmac-titles/",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=title_text,
        title="Title 07 – Health | New Mexico Administrative Code - State Records Center & Archives",
        url="https://www.srca.nm.gov/nmac-home/nmac-titles/title-7-health/",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=chapter_text,
        title="Title 07 – Health | New Mexico Administrative Code - State Records Center & Archives",
        url="https://www.srca.nm.gov/nmac-home/nmac-titles/title-7-health/chapter-34-medical-use-of-cannabis/",
    ) is True
    assert _is_substantive_rule_text(
        text=explanation_text,
        title="Explanation of the New Mexico Administrative Code - State Records Center & Archives",
        url="https://www.srca.nm.gov/nmac-home/explanation-of-the-new-mexico-administrative-code/",
        min_chars=160,
    ) is False
    assert _is_substantive_rule_text(
        text=titles_text,
        title="New Mexico Administrative Code Titles - State Records Center & Archives",
        url="https://www.srca.nm.gov/nmac-home/nmac-titles/",
        min_chars=160,
    ) is False


def test_new_mexico_candidate_url_scoring_prefers_chapter_and_title_over_portal_and_dead_hosts() -> None:
    home_score = _score_candidate_url("https://www.srca.nm.gov/nmac-home/")
    titles_score = _score_candidate_url("https://www.srca.nm.gov/nmac-home/nmac-titles/")
    title_score = _score_candidate_url("https://www.srca.nm.gov/nmac-home/nmac-titles/title-7-health/")
    chapter_score = _score_candidate_url(
        "https://www.srca.nm.gov/nmac-home/nmac-titles/title-7-health/chapter-34-medical-use-of-cannabis/"
    )
    explanation_score = _score_candidate_url(
        "https://www.srca.nm.gov/nmac-home/explanation-of-the-new-mexico-administrative-code/"
    )
    legislature_score = _score_candidate_url("https://legislature.nm.gov/regulations")

    assert titles_score > home_score
    assert title_score > titles_score
    assert chapter_score > title_score
    assert explanation_score < home_score
    assert legislature_score < home_score


def test_south_dakota_inventory_detection_is_limited_to_index_path() -> None:
    text = (
        "Administrative Rules Rule 01:15 TELECOMMUNICATIONS NETWORK Chapter 1:15 1:15:01 Definitions. "
        "1:15:02 Organization and operation of the board. 1:15:03 Site selection procedures. "
        "1:15:04 Telecommunications relay service. 1:15:05 Funding. 1:15:06 Reporting. "
        "1:15:07 Hearings. 1:15:08 Enforcement."
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Administrative Rules | South Dakota Legislature",
        url="https://sdlegislature.gov/Rules/Administrative",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="01:15 TELECOMMUNICATIONS NETWORK",
        url="https://sdlegislature.gov/Rules/Administrative/01:15",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=(
            "20:48:03:01 Application for licensure by examination. An applicant shall submit the required application and fee to the board. "
            "The board may require supporting documentation and verification."
        ),
        title="20:48:03:01 Application for licensure by examination.",
        url="https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx?Rule=20:48:03:01",
    ) is False


def test_tennessee_administrative_register_service_page_is_inventory_not_substantive() -> None:
    text = (
        "Administrative Register The Tennessee Administrative Web site is a register of filings pursuant to the Uniform Administrative Procedures Act. "
        "Current Filings Announcements Emergency Rules Pending Rules Rulemaking Hearing Notices Wildlife Proclamations Archives "
        "Search Past Rule Filings Search Past Rulemaking Hearing Notices Related Services Administrative Register Archive "
        "Effective Rules and Regulations of the State of Tennessee Secretary of State Tre Hargett"
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Administrative Register | Tennessee Secretary of State",
        url="https://sos.tn.gov/publications/services/administrative-register",
    ) is True
    assert _is_substantive_rule_text(
        text=text,
        title="Administrative Register | Tennessee Secretary of State",
        url="https://sos.tn.gov/publications/services/administrative-register",
        min_chars=160,
    ) is False


def test_kansas_publications_hub_is_inventory_page() -> None:
    text = (
        "Kansas Administrative Regulations The Secretary of State is the filing agency for all permanent and temporary regulations. "
        "Online Administrative Regulations Proposed Regulations Open for Comment Future Effective Regulations "
        "Administrative Regulations Agency Resources 2022 Kansas Administrative Regulations Volumes Regulation Modernization Initiative "
        "Kansas Secretary of State Business Services Division Elections Division Publications Division "
        "An official State of Kansas government website. Here's how you know."
    )

    assert scraper_module._looks_like_official_rule_index_page(
        text=text,
        title="Kansas Secretary of State | Publications | Kansas Administrative Regulations Home",
        url="https://www.sos.ks.gov/publications/kansas-administrative-regulations.html",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Kansas Secretary of State | Publications | Kansas Administrative Regulations Home",
        url="https://www.sos.ks.gov/publications/kansas-administrative-regulations.html",
    ) is True
    assert _is_substantive_rule_text(
        text=text,
        title="Kansas Secretary of State | Publications | Kansas Administrative Regulations Home",
        url="https://www.sos.ks.gov/publications/kansas-administrative-regulations.html",
        min_chars=160,
    ) is False


def test_kansas_agency_regulation_resources_page_is_not_substantive_rule_text() -> None:
    text = (
        "Administrative Regulations Agency Resources The Rules and Regulations Filing Act provides the framework for the promulgation, adoption, filing, and publication of permanent and temporary regulations. "
        "Policy and Procedure Manual for Filing Kansas Administrative Rules and Regulations Permanent Regulation Tools Temporary Regulation Tools "
        "Revocation by Notice Tools Other Useful Links Secretary of State Permanent Regulation Filing Checklist "
        "Kansas Secretary of State Publications Division"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Administrative Regulations Agency Resources",
        url="https://www.sos.ks.gov/publications/agency-regulation-resources.html",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Administrative Regulations Agency Resources",
        url="https://www.sos.ks.gov/publications/agency-regulation-resources.html",
    ) is False


def test_kansas_agency_listing_page_is_inventory_not_substantive_text() -> None:
    text = (
        "Kansas Administrative Regulations You searched for: Agency = '7' Agency 7 Secretary of State REGULATIONS "
        "7-16-1. Information and services fee 7-16-2. Technology communication fee 7-17-1. Definitions "
        "7-17-2. Delivery of records 7-17-3. Forms 7-17-4. Fees 7-17-5. Methods of payment "
        "7-17-6. Overpayment and underpayment of fees 7-17-7. Filing officer's duties deemed ministerial "
        "7-17-8. Notification of defects 7-17-9. Defects in filing 7-17-10. Deadline to refuse filing"
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Kansas Administrative Regulations",
        url="https://www.sos.ks.gov/publications/pubs_kar_Regs.aspx?KAR=7&Srch=Y",
    ) is True
    assert _is_substantive_rule_text(
        text=text,
        title="Kansas Administrative Regulations",
        url="https://www.sos.ks.gov/publications/pubs_kar_Regs.aspx?KAR=7&Srch=Y",
        min_chars=160,
    ) is False


def test_wyoming_search_and_program_results_are_inventory_pages() -> None:
    search_body = (
        "Administrative Rules (Code) Agency Accountants Program Accountants Result(s) "
        "Agency Administration Program Human Resources Result(s) "
        "<span class='program_id hidden'>347</span><span class='program_id hidden'>11</span>"
    )
    program_body = (
        '<a href="#" class="search-rule-link" data-whatever="16225">Chapter 1: General Provisions</a>'
        " <strong>Reference Number:</strong> 061.0001.1.10282019 "
        '<a href="#" class="search-rule-link" data-whatever="24261">Chapter 2: Examination</a>'
        " <strong>Reference Number:</strong> 061.0001.2.08082024"
    )

    assert scraper_module._looks_like_official_rule_index_page(
        text=search_body,
        title="Administrative Rules (Code)",
        url="https://rules.wyo.gov/Search.aspx?mode=7",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=search_body,
        title="Administrative Rules (Code)",
        url="https://rules.wyo.gov/Search.aspx?mode=7",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=program_body,
        title="Accountants, Board of Certified Public",
        url="https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules&PROGRAM_ID=347&MODE=7",
    ) is True


def test_arkansas_rule_portals_are_inventory_pages() -> None:
    sos_landing = (
        "Rules & Regulations The Administrative Procedures Act requires state agencies, boards and commissions to file with the Secretary of State. "
        "Search Arkansas Administrative Rules Code of Arkansas Rules State Agency Public Meeting Calendar Agency Rule Filing Instructions Bulk Data Download"
    )
    sos_search = (
        "Search Arkansas Agencies, Boards and Commissions Rules Arkansas Secretary of State Search Results "
        "https://sos-rules-reg.ark.org/rules/pdf/018.00.14-001F-14511.pdf https://sos-rules-reg.ark.org/rules/search/10"
    )
    code_search = "Search - Code of Arkansas Rules Rule Quick Search Title Number Chapter Number"

    assert scraper_module._looks_like_rule_inventory_page(
        text=sos_landing,
        title="Arkansas Secretary of State",
        url="https://www.sos.arkansas.gov/rules-regulations/",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=sos_search,
        title="Search Results - Arkansas Secretary of State",
        url="https://sos-rules-reg.ark.org/rules/search",
    ) is True
    assert scraper_module._looks_like_rule_inventory_page(
        text=code_search,
        title="Search - Code of Arkansas Rules",
        url="https://codeofarrules.arkansas.gov/Rules/Search",
    ) is True


def test_rejects_arkansas_rules_landing_page_as_substantive_rule_text() -> None:
    text = (
        "Rules & Regulations The Administrative Procedures Act requires state agencies, boards and commissions to file with the Secretary of State. "
        "Search Arkansas Administrative Rules Code of Arkansas Rules State Agency Public Meeting Calendar Agency Rule Filing Instructions Bulk Data Download"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Arkansas Secretary of State",
        url="https://www.sos.arkansas.gov/rules-regulations/",
        min_chars=160,
    ) is False


def test_accepts_arkansas_section_rule_page_as_substantive_rule_text() -> None:
    text = (
        "For full functionality of this site it is necessary to enable JavaScript. "
        "Code of Arkansas Rules 2 CAR § 1-101. Purpose Content General Info Notes "
        "2 CAR § 1-101. Purpose. To increase the availability of alternative fuels produced in Arkansas "
        "from feedstock processed in Arkansas by making available incentive grants to: "
        "(1) Alternative fuels producers; (2) Feedstock processors; and (3) Distributors."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="2 CAR § 1-101. Purpose - Code of Arkansas Rules",
        url=(
            "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=section&titleID=2&chapterID=269"
            "&subChapterID=335&partID=1307&subPartID=8275&sectionID=54466"
        ),
        min_chars=160,
    ) is True


def test_candidate_arkansas_rule_urls_from_html_extracts_pdf_and_rule_links() -> None:
    sos_html = """
    <html><body>
      <a href="https://sos-rules-reg.ark.org/rules/pdf/018.00.14-001F-14511.pdf">Final Rule</a>
      <a href="https://sos-rules-reg.ark.org/rules/search/10">Next Page</a>
    </body></html>
    """
    code_html = """
    <html><body>
      <a href="?levelType=title&amp;titleID=1&amp;chapterID=&amp;subChapterID=&amp;partID=&amp;subPartID=&amp;sectionID=">Title 1. General Provisions</a>
    </body></html>
    """

    sos_links = scraper_module._candidate_arkansas_rule_urls_from_html(
        html=sos_html,
        page_url="https://sos-rules-reg.ark.org/rules/search",
        limit=4,
    )
    code_links = scraper_module._candidate_arkansas_rule_urls_from_html(
        html=code_html,
        page_url="https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=9",
        limit=4,
    )

    assert sos_links == [
        "https://sos-rules-reg.ark.org/rules/pdf/018.00.14-001F-14511.pdf",
        "https://sos-rules-reg.ark.org/rules/search/10",
    ]
    assert code_links == [
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=1&chapterID=&subChapterID=&partID=&subPartID=&sectionID=",
    ]


def test_candidate_arkansas_rule_urls_from_html_normalizes_live_sectionid_encoding() -> None:
    code_html = """
    <html><body>
      <a href="?levelType=title&titleID=1&chapterID=&subChapterID=&partID=&subPartID=&sectionID=#rules-tabs-general">Title 1</a>
      <a href="?levelType=title&titleID=2&chapterID=&subChapterID=&partID=&subPartID=&sect;ionID=">Title 2</a>
    </body></html>
    """

    code_links = scraper_module._candidate_arkansas_rule_urls_from_html(
        html=code_html,
        page_url="https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=9",
        limit=4,
    )

    assert code_links == [
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=1&chapterID=&subChapterID=&partID=&subPartID=&sectionID=",
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=2&chapterID=&subChapterID=&partID=&subPartID=&sectionID=",
    ]


def test_score_candidate_url_prioritizes_arkansas_official_rule_hosts_over_dead_legislature_hosts() -> None:
    pdf_score = scraper_module._score_candidate_url(
        "https://sos-rules-reg.ark.org/rules/pdf/018.00.14-001F-14511.pdf"
    )
    title_score = scraper_module._score_candidate_url(
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=1"
    )
    section_score = scraper_module._score_candidate_url(
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=section&titleID=2&chapterID=269&subChapterID=335&partID=1307&subPartID=8275&sectionID=54466"
    )
    dead_score = scraper_module._score_candidate_url("https://legislature.ar.gov/regulations")

    assert pdf_score > dead_score
    assert title_score > dead_score
    assert section_score > title_score


@pytest.mark.asyncio
async def test_discover_arkansas_rule_document_urls_expands_title_tree_to_section_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, *, text: str = "", json_data: Any = None, url: str = "") -> None:
            self.text = text
            self._json_data = json_data
            self.url = url

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._json_data

    class FakeSession:
        def get(self, url, params=None, timeout=0, headers=None):
            if url == "https://codeofarrules.arkansas.gov/Rules/RuleQuickSearch":
                return FakeResponse(
                    text=(
                        '<a href="?levelType=title&amp;titleID=2&amp;chapterID=&amp;subChapterID=&amp;partID=&amp;subPartID=&amp;sectionID=">'
                        'Title 2. Agriculture</a>'
                    ),
                    url="https://codeofarrules.arkansas.gov/Rules/Rule?levelType=title&titleID=2",
                )
            if url == "https://codeofarrules.arkansas.gov/Home/GetRulesTreeViewData":
                level_type = str((params or {}).get("levelType") or "")
                if level_type == "CHAPTER":
                    return FakeResponse(json_data=[{"nodeID": 269, "chapterID": 269}])
                if level_type == "SUBCHAPTER":
                    return FakeResponse(json_data=[{"nodeID": 335, "subchapterID": 335}])
                if level_type == "SECTION":
                    return FakeResponse(
                        json_data=[
                            {
                                "nodeType": "SECTION",
                                "titleID": 2,
                                "chapterID": 269,
                                "subchapterID": 335,
                                "partID": 1307,
                                "subpartID": 8275,
                                "sectionID": 54466,
                            }
                        ]
                    )
            raise AssertionError(f"unexpected request: {url} {params}")

    monkeypatch.setattr(scraper_module.requests, "Session", lambda: FakeSession())

    discovered = await scraper_module._discover_arkansas_rule_document_urls(
        seed_urls=["https://codeofarrules.arkansas.gov/"],
        limit=4,
    )

    assert discovered == [
        "https://codeofarrules.arkansas.gov/Rules/Rule?levelType=section&titleID=2&chapterID=269&subChapterID=335&partID=1307&subPartID=8275&sectionID=54466"
    ]


def test_rejects_wyoming_empty_search_page_as_substantive_rule_text() -> None:
    text = (
        "HOME | ABOUT | HELP | CONTACT | QUICKLINKS | SUBSCRIBE | STATE LOGIN "
        "ADMINISTRATIVE RULES SEARCH Search Clear Fields Current Rules Proposed Rules Emergency Rules "
        "Expired Emergency Rules Superceded Rules Repealed Rules Advanced Search Results (0) No Results Found. "
        "Wyoming Secretary of State 2016 All Rights Reserved."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Administrative Rules Search",
        url="https://rules.wyo.gov/Search.aspx",
        min_chars=160,
    ) is False


def test_rejects_wyoming_rules_landing_page_as_substantive_rule_text() -> None:
    text = (
        "Administrative Rules Advanced Search Current Rules Proposed Rules Emergency Rules HOME | ABOUT | HELP | CONTACT | "
        "QUICKLINKS | SUBSCRIBE | STATE LOGIN ABOUT US The Secretary of State's Office is the repository for rules and regulations, "
        "and provides this centralized system to promote transparency and ease of access to rules by state agencies and the public."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Wyoming Administration Rules",
        url="https://rules.wyo.gov/",
        min_chars=160,
    ) is False


def test_massachusetts_inventory_pages_are_rejected_as_substantive_rule_text() -> None:
    guide_url = "https://www.mass.gov/guides/code-of-massachusetts-regulations-cmr-by-number"
    law_library_url = "https://www.mass.gov/law-library/310-cmr"
    guide_text = (
        "Code of Massachusetts Regulations CMR by number. Browse 105 CMR, 310 CMR, 801 CMR, "
        "and other titles of the Code of Massachusetts Regulations by number."
    )
    law_library_text = (
        "310 CMR. The following regulations are available under 310 CMR. 310 CMR 7.00 Air Pollution Control. "
        "310 CMR 30.00 Hazardous Waste. More regulations and law library resources."
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=guide_text,
        title="Code of Massachusetts Regulations CMR by number",
        url=guide_url,
    ) is True
    assert _is_substantive_rule_text(
        text=guide_text,
        title="Code of Massachusetts Regulations CMR by number",
        url=guide_url,
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=law_library_text,
        title="310 CMR",
        url=law_library_url,
    ) is False


def test_massachusetts_regulation_detail_page_is_direct_and_outscores_inventory() -> None:
    detail_url = "https://www.mass.gov/regulations/310-CMR-700-air-pollution-control-0"
    inventory_url = "https://www.mass.gov/law-library/310-cmr"
    detail_text = (
        "310 CMR 7.00 Air Pollution Control. Organization: Department of Environmental Protection. "
        "Regulatory Authority: M.G.L. c. 111, section 142A. Summary: This regulation establishes air pollution control requirements."
    )

    assert scraper_module._is_direct_detail_candidate_url(detail_url) is True
    assert _is_substantive_rule_text(
        text=detail_text,
        title="310 CMR 7.00: Air Pollution Control",
        url=detail_url,
        min_chars=160,
    ) is True
    assert scraper_module._score_candidate_url(detail_url) > scraper_module._score_candidate_url(inventory_url)


def test_candidate_massachusetts_cmr_urls_from_subject_index_prefers_detail_and_keeps_inventory() -> None:
    html = """
    <table>
        <tr>
            <td>Abortion Services, MassHealth</td>
            <td><a href="/regulations/130-CMR-484000-abortion-clinic-services">130 CMR 484</a></td>
        </tr>
        <tr>
            <td>Abuse of Disabled Person</td>
            <td><a href="/law-library/118-cmr">118 CMR</a></td>
        </tr>
        <tr>
            <td>General Laws</td>
            <td><a href="https://malegislature.gov/Laws/GeneralLaws">MGL</a></td>
        </tr>
    </table>
    """

    urls = _candidate_massachusetts_cmr_urls_from_html(
        html=html,
        page_url="https://www.mass.gov/info-details/code-of-massachusetts-regulations-a-e",
        limit=5,
    )

    assert urls[0] == "https://www.mass.gov/regulations/130-CMR-484000-abortion-clinic-services"
    assert "https://www.mass.gov/law-library/118-cmr" in urls
    assert all("malegislature.gov" not in url for url in urls)


def test_candidate_massachusetts_cmr_urls_from_title_page_returns_detail_links_only() -> None:
    html = """
    <ul>
        <li><a href="/regulations/310-CMR-100-adjudicatory-proceedings-0">310 CMR 1.00: Adjudicatory proceedings</a></li>
        <li><a href="/regulations/310-CMR-500-administrative-penalty">310 CMR 5.00: Administrative penalty</a></li>
        <li><a href="/law-library/310-cmr">310 CMR</a></li>
    </ul>
    """

    urls = _candidate_massachusetts_cmr_urls_from_html(
        html=html,
        page_url="https://www.mass.gov/law-library/310-cmr",
        limit=5,
        include_inventory=False,
    )

    assert urls == [
        "https://www.mass.gov/regulations/310-CMR-100-adjudicatory-proceedings-0",
        "https://www.mass.gov/regulations/310-CMR-500-administrative-penalty",
    ]


def test_rejects_massachusetts_general_laws_pages_as_admin_rules() -> None:
    statute = {
        "code_name": "Code of Massachusetts Regulations",
        "section_name": "General Law - Part I, Title XVI, Chapter 111, Section 142A",
        "source_url": "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXVI/Chapter111/Section142A",
        "full_text": "General Law - Part I, Title XVI, Chapter 111, Section 142A. Authority of the department.",
    }

    assert _is_admin_rule_statute(statute) is False
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_pdf_request_headers_accept_env_cookie_and_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_DOC_REQUEST_USER_AGENT", "Custom Agent/1.0")
    monkeypatch.setenv("IPFS_DATASETS_PY_DOC_REQUEST_COOKIE", "ASPSESSIONID=abc123")

    headers = scraper_module._pdf_request_headers("https://apps.azsos.gov/public_services/Title_01/1-01.pdf")

    assert headers["User-Agent"] == "Custom Agent/1.0"
    assert headers["Cookie"] == "ASPSESSIONID=abc123"
    assert headers["Referer"] == "https://apps.azsos.gov/public_services/CodeTOC.htm"


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


def test_rejects_michigan_rulemaking_transaction_page_as_rule_content() -> None:
    text = (
        "Request For Rulemaking Rule set #: 2021-48 LR Department: Licensing and Regulatory Affairs Bureau: Bureau of Construction Codes "
        "Title of rule set: Construction Code - Part 10. Michigan Uniform Energy Code Filing date: 5/1/2025 Effective date: 8/29/2025 "
        "Request for Rulemaking Draft Rule Language Regulatory Impact Statement Joint Committee on Administrative Rules Package Transcript Approved on: 2/3/2025"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="ARS Public - RFR Transaction",
        url="https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="ARS Public - RFR Transaction",
        url="https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306",
    ) is False


def test_recognizes_michigan_final_rule_returnhtml_as_direct_detail_candidate() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://ars.apps.lara.state.mi.us/Transaction/DownloadFile?FileName=FinalRule%28s%29.pdf&FileType=FinalRule&TransactionID=1306&EffectiveDate=8%2F29%2F2025&ReturnHTML=True"
    ) is True


def test_recognizes_michigan_admincode_returnhtml_as_direct_detail_candidate() -> None:
    assert scraper_module._is_direct_detail_candidate_url(
        "https://ars.apps.lara.state.mi.us/AdminCode/DownloadAdminCodeFile?FileName=R%20338.1%20to%20R%20338.13.pdf&ReturnHTML=True"
    ) is True


def test_score_candidate_url_prioritizes_michigan_final_rule_returnhtml() -> None:
    final_rule_score = scraper_module._score_candidate_url(
        "https://ars.apps.lara.state.mi.us/Transaction/DownloadFile?FileName=FinalRule%28s%29.pdf&FileType=FinalRule&TransactionID=1306&EffectiveDate=8%2F29%2F2025&ReturnHTML=True"
    )
    transaction_score = scraper_module._score_candidate_url(
        "https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306"
    )

    assert final_rule_score > transaction_score


def test_score_candidate_url_prioritizes_michigan_transaction_page_over_admincode_home() -> None:
    transaction_score = scraper_module._score_candidate_url(
        "https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306"
    )
    admincode_home_score = scraper_module._score_candidate_url(
        "https://ars.apps.lara.state.mi.us/AdminCode/AdminCode"
    )

    assert transaction_score > admincode_home_score


def test_score_candidate_url_prioritizes_michigan_admincode_returnhtml_over_department_index() -> None:
    document_score = scraper_module._score_candidate_url(
        "https://ars.apps.lara.state.mi.us/AdminCode/DownloadAdminCodeFile?FileName=R%20338.1%20to%20R%20338.13.pdf&ReturnHTML=True"
    )
    department_score = scraper_module._score_candidate_url(
        "https://ars.apps.lara.state.mi.us/AdminCode/DeptBureauAdminCode?Department=Licensing+and+Regulatory+Affairs&Bureau=All"
    )

    assert document_score > department_score


def test_rejects_michigan_lara_guidance_page_with_site_chrome_as_rule_content() -> None:
    text = (
        "Using the Michigan Administrative Code Scam Alert The Michigan Department of Licensing and Regulatory Affairs will never ask you "
        "to provide your credit card numbers or other personal information over the phone. LARA Licensing and Regulatory Affairs About Us "
        "Bureaus I Need to Learn About News Events Meetings Contact Us."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Using the Michigan Administrative Code",
        url="https://www.michigan.gov/lara/bureau-list/moahr/admin-rules/using-the-michigan-administrative-code",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Using the Michigan Administrative Code",
        url="https://www.michigan.gov/lara/bureau-list/moahr/admin-rules/using-the-michigan-administrative-code",
    ) is False


def test_rejects_michigan_moahr_intro_pdf_as_rule_content() -> None:
    text = "2024 Annual Administrative Code Supplement Introduction Michigan Office of Administrative Hearings and Rules."

    assert _is_substantive_rule_text(
        text=text,
        title="2024 Annual Administrative Code Supplement Introduction",
        url="https://www.michigan.gov/lara/-/media/Project/Websites/lara/moahr/ARD/2024-Annual-Administrative-Code-Supplement/2024_AACS_Intro.pdf",
        min_chars=160,
    ) is False


def test_michigan_elaws_search_page_is_inventory_not_substantive_rule_text() -> None:
    text = (
        "Message loading.. eLaws eCases State of Michigan Search this site by Google Michigan Administrative Code Michigan Register "
        "Department ST State Division Administrative_Hearings. Administrative Hearings Section 11.101. Definitions. "
        "Department IF Insurance and Financial Services Division Insurance. Insurance Section 11.102. Assigned claims facility. "
        "Go To Page Copyright © 2026 by eLaws. All rights reserved."
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Michigan Administrative Code",
        url="http://mirules.elaws.us/search/allcode",
    ) is True
    assert _is_substantive_rule_text(
        text=text,
        title="Michigan Administrative Code",
        url="http://mirules.elaws.us/search/allcode",
        min_chars=160,
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


def test_rejects_tennessee_tn_gov_page_not_found_admin_false_positive() -> None:
    statute = {
        "code_name": "Tennessee Rules and Regulations",
        "section_name": "ERROR: The request could not be satisfied",
        "source_url": "https://www.tn.gov/sos/rules-and-regulations.html",
        "full_text": (
            "ERROR: The request could not be satisfied. Generated by cloudfront. Rules and regulations resources are "
            "not available at this page. Use Tennessee Department of State navigation, publications, and sitemap links "
            "to continue."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert scraper_module._should_emit_relaxed_recovery_statute(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_california_oal_publication_contract_page_as_rule_content() -> None:
    text = (
        "2025 California Code of Regulations and California Regulatory Notice Register Publication Contract. "
        "Notice of Intent to Award Contract. Request for Proposals issued by the Office of Administrative Law. "
        "Sourcing Event 7910-0000036480."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="2025 California Code of Regulations and California Regulatory Notice Register Publication Contract | OAL",
        url="https://oal.ca.gov/publications/2025-california-code-of-regulations-and-california-regulatory-notice-register-publication-contract/",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="2025 California Code of Regulations and California Regulatory Notice Register Publication Contract | OAL",
        url="https://oal.ca.gov/publications/2025-california-code-of-regulations-and-california-regulatory-notice-register-publication-contract/",
    ) is False


def test_rejects_california_oal_ccr_landing_page_as_rule_content() -> None:
    text = (
        "California Code of Regulations (CCR). Online. OAL contracts with Barclays, a division of Thomson-Reuters "
        "to provide a free online version of the Official CCR. Pop-Up Blocker/Westlaw. Documents in Sequence. "
        "Quick Links. Recent Actions Taken By OAL On Regulations."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="California Code of Regulations (CCR) | OAL",
        url="https://oal.ca.gov/publications/ccr/",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="California Code of Regulations (CCR) | OAL",
        url="https://oal.ca.gov/publications/ccr/",
    ) is False


def test_rejects_california_elaws_search_index_as_rule_content() -> None:
    text = (
        "California Code of Regulations loading.. 1 CA Adc T. 1, Div. 2, Chap. 1, Refs & Annos "
        "Title 1 General Provisions Title 2 Administration 1 2 3 ... 6887 6888 Next Go To Page"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="California Code of Regulations",
        url="http://carules.elaws.us/search/allcode",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="California Code of Regulations",
        url="http://carules.elaws.us/search/allcode",
    ) is False


def test_rejects_california_westlaw_index_page_as_rule_content() -> None:
    text = (
        "Skip to Navigation Skip to Main Content California Code of Regulations Home Updates Search Help "
        "California Code of Regulations Title 1. General Provisions Title 2. Administration Title 3. Food and Agriculture "
        "Title 4. Business Regulations Title 5. Education Title 7. Harbors and Navigation Title 8. Industrial Relations "
        "Title 9. Rehabilitative and Developmental Services Privacy Accessibility California Office of Administrative Law"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="California Code of Regulations - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Index?transitionType=Default&contextData=%28sc.Default%29",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="California Code of Regulations - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Index?transitionType=Default&contextData=%28sc.Default%29",
    ) is False
    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="California Code of Regulations - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Index?transitionType=Default&contextData=%28sc.Default%29",
    ) is True


def test_rejects_california_westlaw_division_browse_page_as_rule_content() -> None:
    text = (
        "Skip to Navigation Skip to Main Content California Code of Regulations Home Updates Search Help Home "
        "Title 2. Administration Division 1. Administrative Personnel Division 2. Financial Operations "
        "Division 3. State Property Operations Division 4. Fair Employment and Housing Commission [Renumbered] "
        "Division 4.1. Civil Rights Department Privacy Accessibility California Office of Administrative Law"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Browse - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=IFAACB1F05A0911EC8227000D3A7C4BC3&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Browse - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=IFAACB1F05A0911EC8227000D3A7C4BC3&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)",
    ) is False


def test_rejects_california_westlaw_title_browse_page_as_rule_content() -> None:
    text = (
        "Skip to Navigation Skip to Main Content California Code of Regulations Home Updates Search Help "
        "California Code of Regulations Title 1. General Provisions Title 2. Administration Title 3. Food and Agriculture "
        "Title 4. Business Regulations Title 5. Education Title 7. Harbors and Navigation Title 8. Industrial Relations "
        "Title 9. Rehabilitative and Developmental Services Privacy Accessibility California Office of Administrative Law"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="California Code of Regulations - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=I7C2D715F65E64C2CA1E2A250D9FC3E4C",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="California Code of Regulations - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=I7C2D715F65E64C2CA1E2A250D9FC3E4C",
    ) is False


def test_rejects_california_westlaw_help_page_as_rule_content() -> None:
    text = (
        "California Code of Regulations Help About the California Code of Regulations Site CCR FAQ Technical FAQ Agency List "
        "Contact Us California Legal Products Searching California Code of Regulations Browsing Documents "
        "What is a regulation? What is the difference between a regulation and a statute?"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Help - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Help",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Help - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Help",
    ) is False


def test_rejects_california_westlaw_article_toc_page_as_rule_content() -> None:
    text = (
        "Skip to Navigation Skip to Main Content California Code of Regulations Home Updates Search Help Home "
        "Title 1. General Provisions Division 1. Office of Administrative Law Chapter 1. Review of Proposed Regulations "
        "Article 1. Chapter Definitions § 1. Chapter Definitions. Privacy Accessibility California Office of Administrative Law"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Browse - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=I7DA20CB04C6611ECBA0CE8BD2C3F45C2&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Browse - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=I7DA20CB04C6611ECBA0CE8BD2C3F45C2&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)",
    ) is False
    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="Browse - California Code of Regulations",
        url="https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=I7DA20CB04C6611ECBA0CE8BD2C3F45C2&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)",
    ) is True


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


def test_rejects_montana_chapter_section_listing_with_subchapters() -> None:
    text = (
        "Administrative Rules of Montana\n"
        "Montana Administrative Register\n"
        "Administrative Rules of Montana\n"
        "/\n"
        "Title 1 GENERAL PROVISIONS\n"
        "/\n"
        "Chapter 1.3 ATTORNEY GENERAL MODEL RULES\n"
        "Show Not Effective Rules\n"
        "GENERAL PROVISIONS\n"
        "Chapter 1.1 FOREWORD (REPEALED)\n"
        "Chapter 1.2 GENERAL PROVISIONS (REPEALED)\n"
        "Chapter 1.3 ATTORNEY GENERAL MODEL RULES\n"
        "Subchapter 1.3.1 Procedural Rules Required by MCA Chapter Implementing Article II, Section 8 of the 1972 Constitution - Right of Participation (REPEALED)\n"
        "Subchapter 1.3.2 Attorney General's Organizational and Procedural Rules Required by the Montana Administrative Procedure Act\n"
        "Subchapter 1.3.3 Secretary of State's Organizational and Procedural Rules Required by the Montana Administrative Procedure Act (REPEALED)\n"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="ATTORNEY GENERAL MODEL RULES | Montana SOS",
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/ed446fdb-2d8d-4759-89ac-9cab3b21695c",
        min_chars=160,
    ) is False


def test_synthesizes_montana_rule_urls_from_section_listing() -> None:
    text = (
        '<a href="/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865">1.3.201 INTRODUCTION AND DEFINITIONS</a>'
        '<a href="/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/7c56d2e3-746d-4525-b439-bbfc9c0f5304">1.3.202 APPLICATION OF MONTANA ADMINISTRATIVE PROCEDURE ACT</a>'
        '<a href="/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/be7e2ff7-54c5-4ada-94be-c4fc1a14b13d">1.3.233 GENERAL PROVISIONS, PUBLIC INSPECTION OF ORDERS AND DECISIONS</a>'
    )

    assert _candidate_montana_rule_urls_from_text(
        text=text,
        url="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
        limit=5,
    ) == [
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/7c56d2e3-746d-4525-b439-bbfc9c0f5304",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/be7e2ff7-54c5-4ada-94be-c4fc1a14b13d",
    ]


def test_montana_policy_urls_rank_above_portals_and_are_direct_detail() -> None:
    policy_url = "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865"
    section_url = "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f"
    portal_url = "https://legislature.mt.gov/regulations"

    assert _is_direct_detail_candidate_url(policy_url) is True
    assert _score_candidate_url(policy_url) > _score_candidate_url(section_url)
    assert _score_candidate_url(section_url) > _score_candidate_url(portal_url)


def test_synthesizes_montana_rule_urls_from_sosmt_arm_index() -> None:
    text = (
        '<a href="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f">Title 1</a>'
        '<a href="https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f">Title 1 Duplicate</a>'
        '<a href="https://rules.mt.gov/browse/collections/11111111-2222-3333-4444-555555555555/sections/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">Title 2</a>'
    )

    assert _candidate_montana_rule_urls_from_text(
        text=text,
        url="https://sosmt.gov/arm/",
        limit=5,
    ) == [
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
        "https://rules.mt.gov/browse/collections/11111111-2222-3333-4444-555555555555/sections/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
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


def test_rejects_alabama_admin_code_anchor_hub_as_substantive_rule_text() -> None:
    text = (
        "Alabama Administrative Code Agencies Chapters Rules Administrative Code "
        "Alcoholic Beverage Control Board Agriculture and Industries Chapter 20-X-1 Chapter 20-X-2 "
        "Search Agencies Rules"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Alabama Administrative Code",
        url="https://admincode.legislature.state.al.us/administrative-code#A",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Alabama Administrative Code",
        url="https://admincode.legislature.state.al.us/administrative-code#A",
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


def test_rejects_arizona_rule_index_seo_mirror_false_positive() -> None:
    text = (
        "Website value calculator & SEO Checker => azsos.gov. Is azsos.gov down for everyone or just me? "
        "SEO report with information and free domain appraisal for azsos.gov. Domain Authority. Google Trends. "
        "Estimated worth: 236429 dollars. Remove Website."
    )

    assert _is_relaxed_recovery_text(
        text=text,
        title="azsos.gov? Website value calculator & SEO Checker",
        url="https://azsos.gov/rules/arizona-administrative-code",
    ) is False


def test_rejects_current_arizona_rules_portal_chrome_as_substantive_rule_text() -> None:
    text = (
        "Skip to main content State of Arizona Visit OpenBooks Save with AZRx Main navigation Rules About Search "
        "Tracking Pixel Disclaimer Arizona Administrative Code As Published by the Administrative Rules Division "
        "Table of Contents - Browse by Title and Chapter Subject Index - Search by Keyword Arizona Administrative Code on AMP "
        "Subscriber Info Subscribe Subscribe to our Code Update Email Service"
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Arizona Administrative Code | Arizona Secretary of State",
        url="https://azsos.gov/rules/arizona-administrative-code",
        min_chars=160,
    ) is False


def test_rejects_current_arizona_rules_portal_chrome_as_relaxed_recovery_text() -> None:
    text = (
        "Skip to main content State of Arizona Visit OpenBooks Save with AZRx Main navigation Rules About Search "
        "Tracking Pixel Disclaimer Arizona Administrative Register Published weekly Subscriber Info Subscribe "
        "Subscribe to our Code Update Email Service"
    )

    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Administrative Register | Arizona Secretary of State",
        url="https://azsos.gov/rules/arizona-administrative-register",
    ) is False


def test_should_not_emit_relaxed_recovery_arizona_inventory_page() -> None:
    text = (
        "Arizona Administrative Code. Title 1 State Government. Title 2 Administration. "
        "Title 3 Agriculture. Title 4 Professions and Occupations. Browse the official rules index, "
        "agency rules, notices, and codified administrative materials published by the Arizona Secretary of State."
    )

    assert scraper_module._should_emit_relaxed_recovery_statute(
        text=text,
        title="Arizona Administrative Code",
        url="https://azsos.gov/rules/arizona-administrative-code",
    ) is False


def test_rejects_arizona_admin_register_toc_as_non_rule_page() -> None:
    text = (
        "ARIZONA SECRETARY OF STATE Home / Rules / Arizona Administrative Register / 2025, Volume 31. "
        "Publishing Information. Table of Contents. Issue Date Pages Authenticated PDF. "
        "Rules and Your Rights."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Arizona Administrative Register - 2025",
        url="https://apps.azsos.gov/public_services/Title_02/2-12.pdf",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Administrative Register - 2025",
        url="https://apps.azsos.gov/public_services/Title_02/2-12.pdf",
    ) is False


def test_accepts_arizona_official_chapter_document_with_register_boilerplate() -> None:
    text = (
        "TITLE 18. ENVIRONMENTAL QUALITY CHAPTER 4. DEPARTMENT OF ENVIRONMENTAL QUALITY - SAFE DRINKING WATER "
        "Arizona Administrative Code 18 A.A.C. 4 TITLE 18. ENVIRONMENTAL QUALITY CHAPTER 4. "
        "DEPARTMENT OF ENVIRONMENTAL QUALITY - SAFE DRINKING WATER Page Supp. 25-4 December 31, 2025 "
        "Please note that the Chapter you are about to replace may have rules still in effect after the repeal of this Chapter. "
        "Rules and Your Rights. Article 1. General Provisions. R18-4-101. Definitions."
    )
    url = "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"

    assert scraper_module._looks_like_non_rule_admin_page(
        text=text,
        title="TITLE 18. ENVIRONMENTAL QUALITY",
        url=url,
    ) is False
    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="TITLE 18. ENVIRONMENTAL QUALITY",
        url=url,
    ) is False
    assert _is_substantive_rule_text(
        text=text,
        title="TITLE 18. ENVIRONMENTAL QUALITY",
        url=url,
        min_chars=160,
    ) is True


def test_accepts_arizona_official_pdf_chapter_with_preface_text() -> None:
    text = (
        "Please note that the Chapter you are about to replace may have rules still in effect after the publication date of this supplement. "
        "Therefore, all superseded material should be retained in a separate binder and archived for future reference. "
        "TITLE 7. EDUCATION CHAPTER 2. STATE BOARD OF EDUCATION 7 A.A.C. 2 Supplement Information Supp. 25-4 "
        "Arizona Administrative Code Publisher Department of State Office of the Secretary of State Administrative Rules Division. "
        "Published electronically under the authority of A.R.S. § 41-1012. "
        "Reviewed by the Office editor. Request for Proposals for unrelated services appears in a vendor appendix. "
        "TITLE 7. EDUCATION CHAPTER 2. STATE BOARD OF EDUCATION Authority: A.R.S. § 15-203. "
        "ARTICLE 1. GENERAL PROVISIONS. R7-2-101. Definitions. R7-2-102. Applicability."
    )
    url = "https://apps.azsos.gov/public_services/Title_07/7-02.pdf"

    assert scraper_module._looks_like_non_rule_admin_page(
        text=text,
        title="TITLE 7. EDUCATION",
        url=url,
    ) is False
    assert scraper_module._looks_like_rule_inventory_page(
        text=text,
        title="TITLE 7. EDUCATION",
        url=url,
    ) is False
    assert _is_substantive_rule_text(
        text=text,
        title="TITLE 7. EDUCATION",
        url=url,
        min_chars=160,
    ) is True


def test_rejects_azsos_rules_portal_navigation_wrapper() -> None:
    text = (
        "Skip to main content State of Arizona Visit OpenBooks Ombudsman Citizens Aide "
        "Register to Vote Save with AZRx Main navigation Rules Arizona Administrative Code."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Arizona Administrative Code | Arizona Secretary of State",
        url="https://azsos.gov/rules/arizona-administrative-code",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Administrative Code | Arizona Secretary of State",
        url="https://azsos.gov/rules/arizona-administrative-code",
    ) is False
    assert scraper_module._should_emit_relaxed_recovery_statute(
        text=text,
        title="Arizona Administrative Code | Arizona Secretary of State",
        url="https://azsos.gov/rules/arizona-administrative-code",
    ) is False
    assert scraper_module._should_emit_relaxed_recovery_statute(
        text=text,
        title="Arizona Administrative Register - 2025",
        url="https://apps.azsos.gov/public_services/Title_02/2-12.pdf",
    ) is False


def test_rejects_arizona_legislature_landing_pages_as_relaxed_recovery_text() -> None:
    text = (
        "Arizona Legislature Skip to main content Skip to footer Bill # Search Legislative Events "
        "General Effective Dates IRC 2022 Congressional Maps Bill Process Bill To Law Contact Webmaster"
    )

    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Legislature",
        url="https://legislature.az.gov/regulations",
    ) is False


def test_rejects_www_azleg_root_landing_pages_as_non_rule_text() -> None:
    text = (
        "Arizona Legislature. Home. Rules. Regulations. Policies. Departments. Contact Us. "
        "Skip to main content."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Arizona Administrative Rules",
        url="https://www.azleg.gov/",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Administrative Rules",
        url="https://www.azleg.gov/",
    ) is False


def test_rejects_arizona_public_services_subject_index_as_relaxed_recovery_text() -> None:
    text = (
        "Arizona Administrative Code Subject Index. AAC TOC By Subject List. "
        "Administration, ADEQ. Air Pollution Control, ADEQ. Drinking Water Regulations, Primary and State, ADEQ. "
        "Water Quality Standards, ADEQ. Public Drinking Water System, Capacity Development Requirements, ADEQ."
    )

    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Administrative Code",
        url="https://apps.azsos.gov/public_services/Index/",
    ) is False


def test_rejects_arizona_public_services_subject_index_as_substantive_text() -> None:
    text = (
        "Arizona Administrative Code Subject Index. AAC TOC By Subject List. "
        "Administration, ADEQ. Air Pollution Control, ADEQ. Drinking Water Regulations, Primary and State, ADEQ. "
        "Water Quality Standards, ADEQ. Public Drinking Water System, Capacity Development Requirements, ADEQ."
    )

    assert scraper_module._is_substantive_rule_text(
        text=text,
        title="Arizona Administrative Code",
        url="https://apps.azsos.gov/public_services/Index/",
        min_chars=160,
    ) is False


def test_rejects_arizona_secretary_of_state_rulemaking_meta_chapter_as_rule_content() -> None:
    text = (
        "Arizona Administrative Code Title 1, Ch. 1 Secretary of State - Rules and Rulemaking. "
        "TITLE 1. RULES AND THE RULEMAKING PROCESS. CHAPTER 1. SECRETARY OF STATE RULES AND RULEMAKING. "
        "R1-1-401 Rule Drafting Style and Format. R1-1-502 Notice of Proposed Rulemaking."
    )

    assert _is_substantive_rule_text(
        text=text,
        title="Arizona Administrative Code",
        url="https://apps.azsos.gov/public_services/Title_01/1-01.pdf",
        min_chars=160,
    ) is False
    assert _is_relaxed_recovery_text(
        text=text,
        title="Arizona Administrative Code",
        url="https://apps.azsos.gov/public_services/Title_01/1-01.pdf",
    ) is False


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


def test_candidate_links_from_html_extracts_arizona_official_chapter_document_links_from_flattened_text() -> None:
    flattened = """
    Arizona Administrative Code Subject Index
    AAC TOC By Subject List
    /public_services/Title_18/18-04.pdf
    public_services/Title_18/18-04.rtf
    """

    links = _candidate_links_from_html(
        flattened,
        base_host="apps.azsos.gov",
        page_url="https://apps.azsos.gov/public_services/CodeTOC.htm",
        limit=4,
    )

    assert "https://apps.azsos.gov/public_services/Title_18/18-04.pdf" in links
    assert "https://apps.azsos.gov/public_services/Title_18/18-04.rtf" in links


def test_candidate_links_from_html_ignores_vermont_ruleid_forms() -> None:
    html = """
    <html><body>
        <form action="results.php" method="post">
            <input type="hidden" name="RuleID" value="1050">
        </form>
        <form action="results.php" method="post">
            <input type="hidden" name="RuleID" value="1049">
        </form>
        <a href="search.php">Search Rules</a>
    </body></html>
    """

    links = _candidate_links_from_html(
        html,
        base_host="secure.vermont.gov",
        page_url="https://secure.vermont.gov/SOS/rules/",
        limit=5,
        allowed_hosts={"secure.vermont.gov", "sos.vermont.gov"},
    )

    assert "https://secure.vermont.gov/SOS/rules/display.php?r=1050" not in links
    assert "https://secure.vermont.gov/SOS/rules/display.php?r=1049" not in links


def test_candidate_links_from_html_extracts_vermont_lexis_doc_paths_from_toc() -> None:
    html = """
    <html><body>
        <div data-title="10 000 001. RULES FOR STATE MATCHING FUNDS" data-docfullpath="/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00008-00"></div>
        <div data-title="10 000 002. ANOTHER RULE" data-docfullpath="/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00009-00"></div>
    </body></html>
    """

    links = _candidate_links_from_html(
        html,
        base_host="advance.lexis.com",
        page_url="https://www.lexisnexis.com/hottopics/codeofvtrules/",
        limit=5,
        allowed_hosts={"www.lexisnexis.com", "advance.lexis.com"},
    )

    assert "https://advance.lexis.com/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00008-00" in links
    assert "https://advance.lexis.com/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00009-00" in links


def test_candidate_links_from_html_extracts_wyoming_ajax_program_and_rule_urls() -> None:
        search_html = """
        <html><body>
            <div class="agency_container">
                <span class="program_id hidden">347</span>
                <span class="program_id hidden">11</span>
            </div>
        </body></html>
        """
        program_html = """
        <html><body>
            <a href="#" class="search-rule-link" data-whatever="16225">Chapter 1: General Provisions</a>
            <a href="#" class="search-rule-link" data-whatever="24261">Chapter 2: Examination</a>
        </body></html>
        """

        search_links = _candidate_links_from_html(
                search_html,
                base_host="rules.wyo.gov",
                page_url="https://rules.wyo.gov/Search.aspx?mode=7",
                limit=5,
                allowed_hosts={"rules.wyo.gov"},
        )
        program_links = _candidate_links_from_html(
                program_html,
                base_host="rules.wyo.gov",
                page_url="https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules&PROGRAM_ID=347&MODE=7",
                limit=5,
                allowed_hosts={"rules.wyo.gov"},
        )

        assert "https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules&PROGRAM_ID=347&MODE=7" in search_links
        assert "https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules&PROGRAM_ID=11&MODE=7" in search_links
        assert "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225" in program_links
        assert "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=24261" in program_links


def test_url_key_strips_fragment_identifiers() -> None:
    assert scraper_module._url_key("https://rules.wyo.gov/Search.aspx?mode=7#toTop") == (
        "https://rules.wyo.gov/search.aspx?mode=7"
    )
    assert scraper_module._url_key("https://rules.wyo.gov/Search.aspx?mode=7#ModaltoTop") == (
        "https://rules.wyo.gov/search.aspx?mode=7"
    )


def test_build_initial_pending_candidates_dedupes_canonical_urls_and_keeps_highest_score() -> None:
    pending = scraper_module._build_initial_pending_candidates(
        ranked_urls=[
            ("https://rules.wyo.gov/Search.aspx?mode=7#toTop", 3),
            ("https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225", 8),
        ],
        seed_expansion_candidates=[
            ("https://rules.wyo.gov/Search.aspx?mode=7#ModaltoTop", 9),
            ("https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225", 6),
        ],
        max_candidates=4,
    )

    assert pending == [
        ("https://rules.wyo.gov/Search.aspx?mode=7#ModaltoTop", 9),
        ("https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225", 8),
    ]


def test_candidate_links_from_html_extracts_texas_appian_inventory_and_detail_urls() -> None:
    html = """
    <html><body>
        <a href="?interface=VIEW_TAC&title=1">Title 1</a>
        <a href="?interface=VIEW_TAC&title=1&part=1&chapter=3&subchapter=A">Subchapter A</a>
        <a href="?recordId=204859&queryAsDate=03/14/2026&interface=VIEW_TAC_SUMMARY&$locale=en_US">Rule 1.21</a>
    </body></html>
    """

    links = _candidate_links_from_html(
        html,
        base_host="texas-sos.appianportalsgov.com",
        page_url="https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC",
        limit=10,
        allowed_hosts={"texas-sos.appianportalsgov.com"},
    )

    assert "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC&title=1" in links
    assert (
        "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC&title=1&part=1&chapter=3&subchapter=A"
        in links
    )
    assert (
        "https://texas-sos.appianportalsgov.com/rules-and-meetings?recordId=204859&queryAsDate=03/14/2026&interface=VIEW_TAC_SUMMARY&$locale=en_US"
        in links
    )


def test_scores_arizona_official_chapter_documents_above_inventory_page() -> None:
    inventory_url = "https://apps.azsos.gov/public_services/CodeTOC.htm"
    chapter_pdf_url = "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    chapter_rtf_url = "https://apps.azsos.gov/public_services/Title_01/1-01.rtf"

    assert scraper_module._score_candidate_url(chapter_pdf_url) > scraper_module._score_candidate_url(inventory_url)
    assert scraper_module._score_candidate_url(chapter_rtf_url) > scraper_module._score_candidate_url(inventory_url)


def test_score_candidate_url_prioritizes_wyoming_ajax_rule_pages_over_portals() -> None:
    detail_score = scraper_module._score_candidate_url(
        "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225"
    )
    program_score = scraper_module._score_candidate_url(
        "https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules&PROGRAM_ID=347&MODE=7"
    )
    search_score = scraper_module._score_candidate_url(
        "https://rules.wyo.gov/Search.aspx?mode=7"
    )
    help_score = scraper_module._score_candidate_url(
        "https://rules.wyo.gov/Help/Public/wyoming-administrative-rules-h.html"
    )
    legislature_score = scraper_module._score_candidate_url(
        "https://www.wyoleg.gov/"
    )

    assert detail_score > program_score
    assert program_score > search_score
    assert search_score >= help_score
    assert help_score > legislature_score


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


def test_seed_prefetch_priority_prefers_arizona_direct_documents_and_codetoc() -> None:
    landing_url = "https://azsos.gov/rules/arizona-administrative-code"
    codetoc_url = "https://apps.azsos.gov/public_services/CodeTOC.htm"
    pdf_url = "https://apps.azsos.gov/public_services/Title_07/7-02.pdf"
    rtf_url = "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"

    scored = sorted(
        [landing_url, codetoc_url, pdf_url, rtf_url],
        key=scraper_module._seed_prefetch_priority,
        reverse=True,
    )

    assert scored == [rtf_url, pdf_url, codetoc_url, landing_url]


def test_prioritized_direct_detail_urls_from_candidates_prefers_scored_arizona_docs() -> None:
    candidates = [
        ("https://azsos.gov/rules/arizona-administrative-code", 90),
        ("https://apps.azsos.gov/public_services/CodeTOC.htm", 85),
        ("https://apps.azsos.gov/public_services/Title_07/7-02.pdf", 80),
        ("https://apps.azsos.gov/public_services/Title_18/18-04.rtf", 95),
        ("https://apps.azsos.gov/public_services/Title_18/18-04.rtf", 70),
    ]

    prioritized = scraper_module._prioritized_direct_detail_urls_from_candidates(
        candidates,
        limit=3,
        exclude_urls={"https://apps.azsos.gov/public_services/CodeTOC.htm"},
    )

    assert prioritized == [
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
        "https://apps.azsos.gov/public_services/Title_07/7-02.rtf",
        "https://apps.azsos.gov/public_services/Title_07/7-02.pdf",
    ]


@pytest.mark.asyncio
async def test_extract_text_from_pdf_bytes_uses_repo_pdf_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePDFProcessor:
        def __init__(self, *args, **kwargs):
            assert kwargs.get("enable_audit") is False
            mock_dict = kwargs.get("mock_dict")
            assert isinstance(mock_dict, dict)
            assert set(mock_dict) == {"storage", "integrator", "ocr_engine", "optimizer"}
            assert all(value is not None for value in mock_dict.values())

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
async def test_extract_text_from_pdf_bytes_prefers_pypdf_native_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePdfPage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakePdfReader:
        def __init__(self, stream) -> None:
            self.pages = [
                FakePdfPage("R7-2-101. Definitions. This section defines terms used throughout the chapter."),
                FakePdfPage("Authority: A.R.S. § 15-203. Applicability and enforcement provisions follow in this chapter."),
            ]

    fake_pypdf_module = types.ModuleType("pypdf")
    fake_pypdf_module.PdfReader = FakePdfReader
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf_module)

    class FailingPDFProcessor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("repo PDF processor should not run when pypdf native text succeeds")

    fake_pdf_module = SimpleNamespace(PDFProcessor=FailingPDFProcessor)
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.processors.specialized.pdf", fake_pdf_module)

    extracted = await scraper_module._extract_text_from_pdf_bytes_with_processor(
        b"%PDF-1.4 fake pdf bytes",
        source_url="https://apps.azsos.gov/public_services/Title_07/7-02.pdf",
    )

    assert "R7-2-101. Definitions." in extracted
    assert "Authority: A.R.S. § 15-203." in extracted


@pytest.mark.asyncio
async def test_normalize_candidate_document_content_trims_california_westlaw_chrome() -> None:
    title, text = await scraper_module._normalize_candidate_document_content(
        url="https://govt.westlaw.com/calregs/Document/ICF14695063E711EDB5569A0BCCD916B?viewType=FullText",
        title="View Document - California Code of Regulations",
        text=(
            "Skip to Navigation\nSkip to Main Content\nCalifornia Code of Regulations\n"
            "Home Updates Search Help\nHome Table of Contents\n§ 250. Definitions.\n"
            "Title 1. General Provisions\nDivision 1. Office of Administrative Law\n"
            "Chapter 2. Underground Regulations\n1 CCR § 250\n§ 250. Definitions.\n"
            "Currentness\n1 CA ADC § 250\nBarclays Official California Code of Regulations\n"
            "Authority cited: Government Code section 11342.2. Reference: Government Code section 11342."
        ),
    )

    assert title == "§ 250. Definitions."
    assert text.startswith("§ 250. Definitions.")
    assert "Skip to Navigation" not in text
    assert "Home Updates Search Help" not in text
    assert "Title 1. General Provisions" not in text
    assert "Division 1. Office of Administrative Law" not in text
    assert "Chapter 2. Underground Regulations" not in text
    assert "1 CCR § 250" not in text
    assert "Currentness" not in text
    assert "1 CA ADC § 250" not in text
    assert "Barclays Official California Code of Regulations" not in text


@pytest.mark.asyncio
async def test_normalize_candidate_document_content_trims_indiana_iarp_chrome() -> None:
    title, text = await scraper_module._normalize_candidate_document_content(
        url="https://iar.iga.in.gov/code/current/10/1.5",
        title="Title 10, ARTICLE 1.5. UNCLAIMED PROPERTY | IARP",
        text=(
            "Indiana Administrative Rules and Policies\nHome\nIndiana Register\nAdministrative Code\n"
            "MyIAR\nIndiana Administrative Code\nCurrent\n"
            "TITLE 10 Office of Attorney General for the State\nARTICLE 1 UNCLAIMED PROPERTY SECTION (REPEALED)\n"
            "ARTICLE 1.5 UNCLAIMED PROPERTY\nARTICLE 2 CONTRACT APPROVAL\nTITLE 11 Consumer Protection Division of the Office of the Attorney General\n"
            "TITLE 10 Office of Attorney General for the State\nARTICLE 1.5 UNCLAIMED PROPERTY\nPDF\nCopy Article\n"
            "Article 1\nArticle 2\nTITLE 10 OFFICE OF ATTORNEY GENERAL FOR THE STATE\nARTICLE 1.5. UNCLAIMED PROPERTY\n"
            "Rule 1.\nDefinitions\nRule 2.\nHolders\n10 IAC 1.5-1-1 Applicability\nAuthority: IC 32-34-1.5-87\n"
            "Affected: IC 32-34-1.5\nSec. 1. The definitions in the Unclaimed Property Act and in this rule apply throughout this article.\n"
            "Administrative Drafting Manual\nHistorical List of Executive Orders\nSite Map"
        ),
    )

    assert title == "Title 10, ARTICLE 1.5. UNCLAIMED PROPERTY"
    assert text.startswith("10 IAC 1.5-1-1 Applicability")
    assert "Indiana Administrative Rules and Policies" not in text
    assert "Copy Article" not in text
    assert "Administrative Drafting Manual" not in text


@pytest.mark.asyncio
async def test_normalize_candidate_document_content_trims_rhode_island_ricr_chrome() -> None:
    title, text = await scraper_module._normalize_candidate_document_content(
        url="https://rules.sos.ri.gov/regulations/part/510-00-00-1",
        title="RISBC-1 Rhode Island Building Code - Rhode Island Department of State",
        text=(
            "An Official Rhode Island State Website\nRhode Island Department of State\nGregg M. Amore\n"
            "Secretary of State\nSelect Language\nAbkhaz\nArabic\nRISBC-1 Rhode Island Building Code\n"
            "510-RICR-00-00-1 ACTIVE RULE\nRegulation TextOverviewRegulationHistoryRulemaking Documents\n"
            "1.1 Authority\nAuthority\nR.I. Gen. Laws Chapter 23-27.3 authorizes the building code standards committee to adopt and maintain the state building code.\n"
            "1.2 Incorporated Materials\nThe International Building Code 2021 is incorporated by reference.\n"
            "2002-Current Regulations\nFAQs\nSubscribe to Notifications\nReturn to top\nAdditional Links\n"
            "Business Services\nOpen Government\nPowered by Google Translate Translate"
        ),
    )

    assert title == "RISBC-1 Rhode Island Building Code"
    assert text.startswith("RISBC-1 Rhode Island Building Code")
    assert "An Official Rhode Island State Website" not in text
    assert "Gregg M. Amore" not in text
    assert "Select Language" not in text
    assert "Abkhaz" not in text
    assert "Regulation TextOverviewRegulationHistoryRulemaking Documents" not in text
    assert "Subscribe to Notifications" not in text
    assert "Additional Links" not in text
    assert "Powered by Google Translate" not in text


@pytest.mark.asyncio
async def test_normalize_candidate_document_content_trims_south_dakota_legislature_chrome() -> None:
    title, text = await scraper_module._normalize_candidate_document_content(
        url="https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx?Rule=01:15:01:01",
        title="Administrative Rule 01:15:01:01 | South Dakota Legislature",
        text=(
            "LEGISLATORS\nSESSION\nINTERIM\nLAWS\nADMINISTRATIVE RULES\nBUDGET\nSTUDENTS\nREFERENCES\nMYLRC +\n"
            "Administrative Rules List\nCurrent Register (PDF)\nArchived Registers\nAdministrative Rules Manual\n"
            "Rules Review Committee\nRules.sd.gov\nAdministrative Rules Process (PDF)\n"
            "1:15:01:01. Meaning of terms.\nThe terms used in this article mean:\n(1) \"Board,\" the rural development telecommunications network board of directors."
        ),
    )

    assert title == "1:15:01:01. Meaning of terms."
    assert text.startswith("1:15:01:01. Meaning of terms.")
    assert "LEGISLATORS" not in text
    assert "Administrative Rules List" not in text
    assert "Rules.sd.gov" not in text


@pytest.mark.asyncio
async def test_normalize_candidate_document_content_trims_indiana_expired_article_to_notice() -> None:
    title, text = await scraper_module._normalize_candidate_document_content(
        url="https://iar.iga.in.gov/code/current/16/2",
        title="Title 16, ARTICLE 2. INDIANA RESIDENTIAL CONSERVATION SERVICE PROGRAM (EXPIRED) | IARP",
        text=(
            "Indiana Administrative Rules and Policies\nHome\nIndiana Register\nAdministrative Code\nMyIAR\n"
            "Indiana Administrative Code\nCurrent\nTITLE 10 Office of Attorney General for the State\n"
            "TITLE 16 Office of the Lieutenant Governor\nARTICLE 1 ENERGY DEVELOPMENT BOARD (EXPIRED)\n"
            "ARTICLE 2 INDIANA RESIDENTIAL CONSERVATION SERVICE PROGRAM (EXPIRED)\nARTICLE 3 SOLAR ENERGY INCOME TAX CREDIT (EXPIRED)\n"
            "TITLE 16 Office of the Lieutenant Governor\nARTICLE 2 INDIANA RESIDENTIAL CONSERVATION SERVICE PROGRAM (EXPIRED)\n"
            "PDF\nCopy Article\nArticle 1\nArticle 3\nTITLE 16 OFFICE OF THE LIEUTENANT GOVERNOR\n"
            "ARTICLE 2. INDIANA RESIDENTIAL CONSERVATION SERVICE PROGRAM (EXPIRED)\n"
            "(Expired under IC 4-22-2.5, effective January 1, 2009.)\n"
            "Administrative Drafting Manual\nHistorical List of Executive Orders\nSite Map"
        ),
    )

    assert title == "Title 16, ARTICLE 2. INDIANA RESIDENTIAL CONSERVATION SERVICE PROGRAM (EXPIRED)"
    assert text.startswith("ARTICLE 2 INDIANA RESIDENTIAL CONSERVATION SERVICE PROGRAM (EXPIRED)")
    assert "Copy Article" not in text
    assert "Administrative Drafting Manual" not in text
    assert _is_substantive_rule_text(
        text=text,
        title=title,
        url="https://iar.iga.in.gov/code/current/16/2",
        min_chars=160,
    ) is False


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
async def test_extract_text_from_rtf_bytes_prefers_trimmed_legal_content_over_noisy_front_matter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRTFResult:
        success = True
        text = (
            "Times New Roman; Arial; Cambria Math; Default Paragraph Font; "
            "Normal Table; panose 02020603050405020304"
        )

    class FakeRTFExtractor:
        def extract(self, file_path):
            return FakeRTFResult()

    monkeypatch.setattr(file_converter_module, "RTFExtractor", FakeRTFExtractor)

    front_matter = ("Times New Roman; Arial; Cambria Math; Default Paragraph Font; Normal Table; panose " * 80)
    rtf_bytes = (
        "{\\rtf1\\ansi "
        f"{front_matter}"
        "\\par CHAPTER 4. DEPARTMENT OF ENVIRONMENTAL QUALITY - SAFE DRINKING WATER"
        "\\par ARTICLE 1. PRIMARY DRINKING WATER REGULATIONS"
        "\\par R18-4-101. Applicability and definitions."
        "}"
    ).encode("latin1")

    extracted = await scraper_module._extract_text_from_rtf_bytes_with_processor(
        rtf_bytes,
        source_url="https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    )

    assert extracted.startswith("CHAPTER 4. DEPARTMENT OF ENVIRONMENTAL QUALITY - SAFE DRINKING WATER")
    assert "R18-4-101. Applicability and definitions." in extracted


@pytest.mark.asyncio
async def test_extract_text_from_rtf_bytes_repairs_split_words_in_salvaged_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRTFResult:
        success = True
        text = (
            "TITLE 18. ENVIRONMENTAL QUALI TY\nArizona Adm inistrative Code\n"
            "A pril 1, 2023\nThe Code is separated by subjec t into Titles."
        )

    class FakeRTFExtractor:
        def extract(self, file_path):
            return FakeRTFResult()

    monkeypatch.setattr(file_converter_module, "RTFExtractor", FakeRTFExtractor)

    extracted = await scraper_module._extract_text_from_rtf_bytes_with_processor(
        (
            b"{\\rtf1\\ansi TITLE 18. ENVIRONMENTAL QUALI TY\\par Arizona Adm inistrative Code"
            b"\\par A pril 1, 2023\\par The Code is separated by subjec t into Titles.}"
        ),
        source_url="https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    )

    assert "QUALITY" in extracted
    assert "Administrative Code" in extracted
    assert "April 1, 2023" in extracted
    assert "subject into Titles" in extracted
    assert "QUALI TY" not in extracted
    assert "Adm inistrative" not in extracted
    assert "A pril" not in extracted
    assert "subjec t" not in extracted


@pytest.mark.asyncio
async def test_extract_text_from_rtf_bytes_rejects_cloudflare_challenge_html() -> None:
    extracted = await scraper_module._extract_text_from_rtf_bytes_with_processor(
        b"<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>Enable JavaScript and cookies to continue</body></html>",
        source_url="https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    )

    assert extracted == ""


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
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_cloudscraper", lambda url: None)
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_playwright", fake_download)
    monkeypatch.setattr(scraper_module, "_extract_text_from_pdf_bytes_with_processor", fake_extract)

    scraped = await scraper_module._scrape_pdf_candidate_url_with_processor(
        "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    )

    assert scraped is not None
    assert scraped.method_used == "pdf_processor_playwright_download"
    assert "Authority and definitions." in scraped.text


@pytest.mark.asyncio
async def test_discover_alabama_rule_document_urls_uses_public_code_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict[str, Any]):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    calls: list[dict[str, Any]] = []

    def fake_post(url: str, timeout: int, headers: dict[str, str], json: dict[str, Any]):
        calls.append({"url": url, "json": json})
        operation_name = json.get("operationName")
        if operation_name == "agencySortTitles":
            return FakeResponse(
                {
                    "data": {
                        "agencies": [
                            {"controlNumber": "20", "shown": True, "sortableTitle": "Alcoholic Beverage Control Board, Alabama"},
                        ]
                    }
                }
            )
        if operation_name == "publicCode":
            return FakeResponse(
                {
                    "data": {
                        "document": {
                            "__typename": "Agency",
                            "chapters": [
                                {
                                    "idText": "20-X-2",
                                    "title": "General Provisions",
                                    "rules": [
                                        {"idText": "20-X-2-.01", "title": "Glossary Of Terms"},
                                        {"idText": "20-X-2-.02", "title": "Possession Of ABC Board Regulations On Licensed Premises"},
                                    ],
                                }
                            ],
                        }
                    }
                }
            )
        raise AssertionError(f"unexpected operation: {operation_name}")

    monkeypatch.setattr(scraper_module.requests, "post", fake_post)

    urls = await scraper_module._discover_alabama_rule_document_urls(limit=2)

    assert urls == [
        "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01",
        "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.02",
    ]
    assert calls[0]["json"]["extensions"]["persistedQuery"]["sha256Hash"] == scraper_module._AL_AGENCY_SORT_TITLES_HASH
    assert calls[1]["json"]["extensions"]["persistedQuery"]["sha256Hash"] == scraper_module._AL_PUBLIC_CODE_HASH


@pytest.mark.asyncio
async def test_discover_indiana_rule_document_urls_uses_public_tree_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict[str, Any]):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    calls: list[dict[str, Any]] = []

    def fake_get(url: str, timeout: int, headers: dict[str, str], params: dict[str, Any] | None = None):
        calls.append({"url": url, "headers": headers, "params": params})
        if url.endswith("/adminCodeEditions"):
            return FakeResponse(
                {
                    "iar_iac_edition_list": [
                        {"edition_year": 2024},
                        {"edition_year": 2027},
                    ]
                }
            )
        if url.endswith("/adminCodeTree"):
            assert params == {"edition_year": 2027, "doc_stage": "public"}
            return FakeResponse(
                {
                    "iar_iac_title_article_list": [
                        {
                            "title_num": "10",
                            "article": [
                                {"article_num": "1", "article_name": "ARTICLE 1. OLD RULE (REPEALED)"},
                                {"article_num": "1.5", "article_name": "ARTICLE 1.5. UNCLAIMED PROPERTY"},
                                {"article_num": "2", "article_name": "ARTICLE 2. CONTRACT APPROVAL"},
                            ],
                        }
                    ]
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    urls = await scraper_module._discover_indiana_rule_document_urls(limit=2)

    assert urls == [
        "https://iar.iga.in.gov/code/current/10/1.5",
        "https://iar.iga.in.gov/code/current/10/2",
    ]
    assert calls[0]["headers"]["Origin"] == "https://iar.iga.in.gov"
    assert "Chrome/142.0.0.0" in calls[0]["headers"]["User-Agent"]


@pytest.mark.asyncio
async def test_discover_montana_rule_document_urls_expands_section_tree_via_public_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    calls: list[str] = []

    def fake_get(url: str, timeout: int, headers: dict[str, str]):
        calls.append(url)
        if url.endswith("/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/11111111-2222-3333-4444-555555555555"):
            return FakeResponse(
                {
                    "uuid": "11111111-2222-3333-4444-555555555555",
                    "childSections": [
                        {"uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
                        {"uuid": "ffffffff-1111-2222-3333-444444444444"},
                    ],
                    "childPolicies": [],
                }
            )
        if url.endswith("/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"):
            return FakeResponse(
                {
                    "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "childSections": [],
                    "childPolicies": [
                        {"uuid": "12345678-1111-2222-3333-444444444444"},
                        {"uuid": "87654321-aaaa-bbbb-cccc-dddddddddddd"},
                    ],
                }
            )
        if url.endswith("/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/ffffffff-1111-2222-3333-444444444444"):
            return FakeResponse(
                {
                    "uuid": "ffffffff-1111-2222-3333-444444444444",
                    "childSections": [],
                    "childPolicies": [{"uuid": "99999999-8888-7777-6666-555555555555"}],
                }
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    urls = await scraper_module._discover_montana_rule_document_urls(
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/11111111-2222-3333-4444-555555555555",
        limit=2,
    )

    assert urls == [
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/12345678-1111-2222-3333-444444444444",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/87654321-aaaa-bbbb-cccc-dddddddddddd",
    ]
    assert calls[0].endswith("/sections/11111111-2222-3333-4444-555555555555")


@pytest.mark.anyio
async def test_agentic_discovery_bootstraps_montana_public_api_policy_urls_from_seed_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/11111111-2222-3333-4444-555555555555"
    policy_url = "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/12345678-1111-2222-3333-444444444444"
    archive_calls = 0
    unified_search_calls = 0
    agentic_calls = 0
    fetch_calls = 0
    scrape_domain_calls = 0

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            nonlocal archive_calls
            archive_calls += 1
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            nonlocal unified_search_calls
            unified_search_calls += 1
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            nonlocal agentic_calls
            agentic_calls += 1
            return {"results": []}

        def fetch(self, request):
            nonlocal fetch_calls
            fetch_calls += 1
            document = SimpleNamespace(
                text="",
                title="",
                html="",
                extraction_provenance={"method": "requests_only"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(text="", title="", html="", links=[])

        async def scrape_domain(self, url: str, max_pages: int = 0):
            nonlocal scrape_domain_calls
            scrape_domain_calls += 1
            return []

    async def _fake_discover_montana_rule_document_urls(url: str, *, limit: int = 8) -> list[str]:
        assert url == seed_url
        assert limit >= 1
        return [policy_url]

    async def _fake_scrape_montana_rule_detail_via_api(url: str):
        assert url == policy_url
        return SimpleNamespace(
            text=("Administrative Rules of Montana\n1.3.201 INTRODUCTION AND DEFINITIONS\n" * 8).strip(),
            title="1.3.201 INTRODUCTION AND DEFINITIONS | Montana SOS",
            html="<html><body>Administrative Rules of Montana</body></html>",
            links=[],
            method_used="montana_public_policy_api",
            extraction_provenance={"method": "montana_public_policy_api"},
        )

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_discover_montana_rule_document_urls", _fake_discover_montana_rule_document_urls)
    monkeypatch.setattr(scraper_module, "_scrape_montana_rule_detail_via_api", _fake_scrape_montana_rule_detail_via_api)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
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
        states=["MT"],
        max_candidates_per_state=4,
        max_fetch_per_state=6,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=160,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] >= 1
    assert result["report"]["MT"]["fetched_rules"] >= 1
    assert result["report"]["MT"]["source_breakdown"]["montana_public_api_bootstrap"] == 1
    assert result["report"]["MT"]["top_candidate_urls"][0] == policy_url
    assert archive_calls == 0
    assert unified_search_calls == 0
    assert agentic_calls == 0
    assert scrape_domain_calls == 0


@pytest.mark.anyio
async def test_agentic_discovery_bootstraps_michigan_admincode_rule_urls_before_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://ars.apps.lara.state.mi.us/AdminCode/AdminCode"
    rule_url = (
        "https://ars.apps.lara.state.mi.us/AdminCode/DownloadAdminCodeFile?"
        "FileName=R%20338.1%20to%20R%20338.13.pdf&ReturnHTML=True"
    )
    archive_calls = 0
    unified_search_calls = 0
    agentic_calls = 0

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            nonlocal archive_calls
            archive_calls += 1
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            nonlocal unified_search_calls
            unified_search_calls += 1
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            nonlocal agentic_calls
            agentic_calls += 1
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text="",
                title="",
                html="",
                extraction_provenance={"method": "requests_only"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            assert url == rule_url
            return SimpleNamespace(
                text=("Michigan Administrative Code\nLicensing Rules\n" * 8).strip(),
                title="Michigan Admin Code Download",
                html="<html><body>Michigan Administrative Code</body></html>",
                links=[],
                method_used="requests_only",
                extraction_provenance={"method": "requests_only"},
            )

        async def scrape_domain(self, url: str, max_pages: int = 0):
            raise AssertionError("scrape_domain should not run when Michigan bootstrap succeeds")

    async def _fake_discover_michigan_rule_document_urls(*, seed_urls: list[str], limit: int = 8) -> list[str]:
        assert seed_urls == [seed_url]
        assert limit >= 1
        return [rule_url]

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_discover_michigan_rule_document_urls", _fake_discover_michigan_rule_document_urls)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
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
        states=["MI"],
        max_candidates_per_state=4,
        max_fetch_per_state=6,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=160,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] >= 1
    assert result["report"]["MI"]["fetched_rules"] >= 1
    assert result["report"]["MI"]["source_breakdown"]["michigan_admincode_bootstrap"] == 1
    assert result["report"]["MI"]["top_candidate_urls"][0] == rule_url
    assert archive_calls == 0
    assert unified_search_calls == 0
    assert agentic_calls == 0


@pytest.mark.anyio
async def test_agentic_discovery_bootstraps_alaska_print_rule_urls_before_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://www.akleg.gov/basis/aac.asp"
    rule_url = "https://www.akleg.gov/basis/aac.asp?media=print&secStart=1.05.010&secEnd=1.05.010"
    archive_calls = 0
    unified_search_calls = 0
    agentic_calls = 0

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            nonlocal archive_calls
            archive_calls += 1
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            nonlocal unified_search_calls
            unified_search_calls += 1
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            nonlocal agentic_calls
            agentic_calls += 1
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text="",
                title="",
                html="",
                extraction_provenance={"method": "requests_only"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            assert url == rule_url
            return SimpleNamespace(
                text=("Alaska Administrative Code\n1 AAC 05.010\n" * 8).strip(),
                title="1 AAC 05.010",
                html="<html><body>Alaska Administrative Code</body></html>",
                links=[],
                method_used="requests_only",
                extraction_provenance={"method": "requests_only"},
            )

        async def scrape_domain(self, url: str, max_pages: int = 0):
            raise AssertionError("scrape_domain should not run when Alaska bootstrap succeeds")

    async def _fake_discover_alaska_rule_document_urls(*, seed_urls: list[str], limit: int = 8) -> list[str]:
        assert seed_urls == [seed_url]
        assert limit >= 1
        return [rule_url]

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_discover_alaska_rule_document_urls", _fake_discover_alaska_rule_document_urls)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
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
        states=["AK"],
        max_candidates_per_state=4,
        max_fetch_per_state=6,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=160,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] >= 1
    assert result["report"]["AK"]["fetched_rules"] >= 1
    assert result["report"]["AK"]["source_breakdown"]["alaska_print_view_bootstrap"] == 1
    assert result["report"]["AK"]["top_candidate_urls"][0] == rule_url
    assert archive_calls == 0
    assert unified_search_calls == 0
    assert agentic_calls == 0


@pytest.mark.asyncio
async def test_discover_michigan_rule_document_urls_expands_admincode_home_to_returnhtml_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self) -> None:
            return None

    admincode_home = "https://ars.apps.lara.state.mi.us/AdminCode/AdminCode"
    licensing_all = (
        "https://ars.apps.lara.state.mi.us/AdminCode/DeptBureauAdminCode?"
        "Department=Licensing+and+Regulatory+Affairs&Bureau=All"
    )

    def fake_get(url: str, timeout: int, headers: dict[str, str]):
        if url == admincode_home:
            return FakeResponse(
                """
                <html><body>
                    <select name=\"Department\">
                        <option value=\"Select Department\">Select Department</option>
                        <option value=\"Licensing and Regulatory Affairs\">Licensing and Regulatory Affairs</option>
                    </select>
                </body></html>
                """
            )
        if url == licensing_all:
            return FakeResponse(
                """
                <html><body>
                    <a href=\"/AdminCode/DownloadAdminCodeFile?FileName=R%20338.1%20to%20R%20338.13.pdf&ReturnHTML=True\">HTML</a>
                    <a href=\"/AdminCode/DownloadAdminCodeFile?FileName=R%20338.111%20to%20R%20338.143.pdf&ReturnHTML=True\">HTML</a>
                </body></html>
                """
            )
        raise AssertionError(url)

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    urls = await scraper_module._discover_michigan_rule_document_urls(seed_urls=[admincode_home], limit=2)

    assert urls == [
        "https://ars.apps.lara.state.mi.us/AdminCode/DownloadAdminCodeFile?FileName=R%20338.1%20to%20R%20338.13.pdf&ReturnHTML=True",
        "https://ars.apps.lara.state.mi.us/AdminCode/DownloadAdminCodeFile?FileName=R%20338.111%20to%20R%20338.143.pdf&ReturnHTML=True",
    ]


@pytest.mark.asyncio
async def test_discover_alaska_rule_document_urls_expands_toc_to_print_section_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

    class FakeSession:
        def get(self, url: str, timeout: int, headers: dict[str, str]):
            if url == "https://www.akleg.gov/basis/aac.asp":
                return FakeResponse("<a onclick=\"loadTOC(' 1')\">Title 1</a>")
            if url == "https://www.akleg.gov/basis/aac.asp?media=js&type=TOC&title=1":
                return FakeResponse('<a onclick=loadTOC("1.05")>Chapter 05</a>')
            if url == "https://www.akleg.gov/basis/aac.asp?media=js&type=TOC&title=1.05":
                return FakeResponse(
                    '<a onclick="closeTOC();checkLink(\'1.05.010\'); ">Sec. 1 AAC 05.010</a>'
                    '<a onclick="closeTOC();checkLink(\'1.05.020\'); ">Sec. 1 AAC 05.020</a>'
                )
            raise AssertionError(url)

    monkeypatch.setattr(scraper_module.requests, "Session", lambda: FakeSession())

    urls = await scraper_module._discover_alaska_rule_document_urls(
        seed_urls=["https://www.akleg.gov/basis/aac.asp"],
        limit=2,
    )

    assert urls == [
        "https://www.akleg.gov/basis/aac.asp?media=print&secStart=1.05.010&secEnd=1.05.010",
        "https://www.akleg.gov/basis/aac.asp?media=print&secStart=1.05.020&secEnd=1.05.020",
    ]


@pytest.mark.asyncio
async def test_scrape_alabama_rule_detail_via_api_uses_public_code_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "data": {
                    "document": {
                        "__typename": "Rule",
                        "idText": "20-X-2-.01",
                        "title": "Glossary Of Terms",
                        "description": "<p>Alcoholic beverages are defined for this chapter.</p>",
                        "authority": "Code of Ala. 1975, Section 28-3-49.",
                        "history": "Filed January 1, 2024.",
                        "penalty": "None.",
                        "editorsNote": "Editorial note.",
                    }
                }
            }

    requests_seen: list[dict[str, Any]] = []

    def fake_post(url: str, timeout: int, headers: dict[str, str], json: dict[str, Any]):
        requests_seen.append(json)
        return FakeResponse()

    monkeypatch.setattr(scraper_module.requests, "post", fake_post)

    scraped = await scraper_module._scrape_alabama_rule_detail_via_api(
        "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01"
    )

    assert scraped is not None
    assert scraped.title == "20-X-2-.01 Glossary Of Terms"
    assert "Alcoholic beverages are defined" in scraped.text
    assert "Authority:" in scraped.text
    assert scraped.method_used == "alabama_public_code_api"
    assert requests_seen[0]["operationName"] == "publicCode"
    assert requests_seen[0]["extensions"]["persistedQuery"]["sha256Hash"] == scraper_module._AL_PUBLIC_CODE_HASH


@pytest.mark.asyncio
async def test_scrape_indiana_rule_detail_via_api_uses_public_article_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict[str, Any]):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    calls: list[dict[str, Any]] = []

    def fake_get(url: str, timeout: int, headers: dict[str, str], params: dict[str, Any] | None = None):
        calls.append({"url": url, "headers": headers, "params": params})
        if url.endswith("/adminCodeArticle"):
            assert params == {
                "doc_stage": "public",
                "edition_year": 2027,
                "title_num": "10",
                "article_num": "1.5",
            }
            return FakeResponse(
                {
                    "iar_iac_article_doc": {
                        "title_num": "10",
                        "title_name": "Office of Attorney General for the State",
                        "article_name": "ARTICLE 1.5. UNCLAIMED PROPERTY",
                        "doc_html": (
                            "<h1>TITLE 10 OFFICE OF ATTORNEY GENERAL FOR THE STATE</h1>"
                            "<h1>ARTICLE 1.5. UNCLAIMED PROPERTY</h1>"
                            "<div>Authority: IC 32-34-1.5-87</div>"
                            "<div>Sec. 1. The definitions in the Unclaimed Property Act apply.</div>"
                        ),
                    }
                }
            )
        if url.endswith("/adminCodeEditions"):
            return FakeResponse({"iar_iac_edition_list": [{"edition_year": 2027}]})
        raise AssertionError(url)

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    scraped = await scraper_module._scrape_indiana_rule_detail_via_api(
        "https://iar.iga.in.gov/code/current/10/1.5"
    )

    assert scraped is not None
    assert scraped.title == "Title 10 ARTICLE 1.5. UNCLAIMED PROPERTY, Office of Attorney General for the State"
    assert "Sec. 1. The definitions in the Unclaimed Property Act apply." in scraped.text
    assert scraped.method_used == "indiana_admin_code_api"
    article_call = next(call for call in calls if call["url"].endswith("/adminCodeArticle"))
    assert article_call["headers"]["Referer"] == "https://iar.iga.in.gov/code/current/10/1.5"


@pytest.mark.asyncio
async def test_scrape_montana_rule_detail_via_api_uses_public_policy_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(self, *, payload: dict[str, object] | None = None, text: str = "", content: bytes = b"", headers: dict[str, str] | None = None):
            self._payload = payload
            self.text = text
            self.content = content
            self.headers = headers or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            assert self._payload is not None
            return self._payload

    calls: list[str] = []

    def fake_get(url: str, timeout: int, headers: dict[str, str]):
        calls.append(url)
        if url.endswith("/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865"):
            return FakeResponse(
                payload={
                    "policy": {
                        "uuid": "51f36d4d-ca58-49bf-bf41-e1881edd4865",
                        "currentVersionUuid": "version-1",
                        "citationId": "1.3.201",
                        "name": "INTRODUCTION AND DEFINITIONS",
                        "fields": [
                            {"label": "Contact Information", "value": "contactdoj@mt.gov"},
                        ],
                        "policyVersions": [
                            {
                                "uuid": "version-1",
                                "isActive": True,
                                "subStatuses": ["EFFECTIVE"],
                                "fields": [
                                    {"label": "Rule History", "value": "Eff. 12/31/72; AMD, 2009 MAR p. 7, Eff. 1/16/09."},
                                ],
                                "accessibleHtmlDocument": {
                                    "contentType": "text/html",
                                    "contentUrl": "/api/policy-library-public/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865/document/html-1",
                                },
                            }
                        ],
                    }
                }
            )
        if url.endswith("/document/html-1"):
            return FakeResponse(
                text=(
                    "<html><body><div id='documentBody'>"
                    "<p><strong>1.3.201 INTRODUCTION AND DEFINITIONS</strong></p>"
                    "<p>Authority: 2-4-201, MCA</p>"
                    "<p>(1) These rules govern attorney general model procedures.</p>"
                    "</div></body></html>"
                ),
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    scraped = await scraper_module._scrape_montana_rule_detail_via_api(
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865"
    )

    assert scraped is not None
    assert scraped.title == "1.3.201 INTRODUCTION AND DEFINITIONS"
    assert "These rules govern attorney general model procedures." in scraped.text
    assert "Rule History: Eff. 12/31/72; AMD, 2009 MAR p. 7, Eff. 1/16/09." in scraped.text
    assert "Status: EFFECTIVE" in scraped.text
    assert scraped.method_used == "montana_public_policy_api"
    assert calls[0].endswith("/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865")


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


def test_download_document_bytes_via_cloudscraper_falls_back_to_cfscrape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ChallengeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = b"<html><title>Just a moment...</title></html>"

    class PdfResponse:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        content = b"%PDF-1.4 cfscrape bytes"

    class FakeCloudscraperSession:
        def get(self, url, timeout=0, headers=None):
            return ChallengeResponse()

    class FakeCloudscraperModule:
        @staticmethod
        def create_scraper(browser=None):
            return FakeCloudscraperSession()

    class FakeCfscrapeSession:
        def get(self, url, timeout=0, headers=None):
            return PdfResponse()

    class FakeCfscrapeModule:
        @staticmethod
        def create_scraper():
            return FakeCfscrapeSession()

    monkeypatch.setitem(sys.modules, "cloudscraper", FakeCloudscraperModule)
    monkeypatch.setitem(sys.modules, "cfscrape", FakeCfscrapeModule)

    fetched = scraper_module._download_document_bytes_via_cloudscraper(
        "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    )

    assert fetched == {
        "body": b"%PDF-1.4 cfscrape bytes",
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


def test_playwright_storage_state_path_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_PLAYWRIGHT_STORAGE_STATE", "/tmp/storage-state.json")

    assert scraper_module._playwright_storage_state_path().as_posix() == "/tmp/storage-state.json"


def test_playwright_cookie_header_falls_back_to_doc_request_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_PLAYWRIGHT_COOKIE_HEADER", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_DOC_REQUEST_COOKIE", "ASPSESSIONID=abc123")

    assert scraper_module._playwright_cookie_header() == "ASPSESSIONID=abc123"


def test_playwright_cookies_from_header_parses_cookie_pairs() -> None:
    cookies = scraper_module._playwright_cookies_from_header(
        "https://apps.azsos.gov/public_services/Title_01/1-01.pdf",
        "ASPSESSIONID=abc123; foo=bar",
    )

    assert cookies == [
        {
            "name": "ASPSESSIONID",
            "value": "abc123",
            "domain": "apps.azsos.gov",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
        {
            "name": "foo",
            "value": "bar",
            "domain": "apps.azsos.gov",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
    ]


def test_playwright_persistent_profile_mode_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_PLAYWRIGHT_USE_PERSISTENT_PROFILE", raising=False)

    assert scraper_module._use_persistent_playwright_profile() is True


def test_playwright_headless_mode_can_be_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_PLAYWRIGHT_HEADLESS", "0")

    assert scraper_module._playwright_headless_enabled() is False


@pytest.mark.asyncio
async def test_download_document_bytes_via_playwright_prefers_immediate_page_fetch_after_referer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def __init__(self):
            self.goto_calls = []

        async def goto(self, url, wait_until=None, timeout=None):
            self.goto_calls.append((url, wait_until, timeout))

    class FakeContext:
        def __init__(self, page):
            self._page = page
            self.pages = []

        async def new_page(self):
            return self._page

        async def close(self):
            return None

        async def add_cookies(self, cookies):
            return None

    class FakeBrowser:
        def __init__(self, context):
            self._context = context

        async def new_context(self, **kwargs):
            return self._context

        async def close(self):
            return None

    class FakeChromium:
        def __init__(self, browser):
            self._browser = browser

        async def launch(self, **kwargs):
            return self._browser

    class FakePlaywright:
        def __init__(self, browser):
            self.chromium = FakeChromium(browser)

    class FakePlaywrightManager:
        def __init__(self, browser):
            self._playwright = FakePlaywright(browser)

        async def __aenter__(self):
            return self._playwright

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_page = FakePage()
    fake_context = FakeContext(fake_page)
    fake_browser = FakeBrowser(fake_context)
    fake_async_api = SimpleNamespace(async_playwright=lambda: FakePlaywrightManager(fake_browser))
    page_fetch_calls = []

    async def fake_apply_session_state(context, page, url):
        return None

    async def fake_page_fetch(page, url):
        page_fetch_calls.append((page, url))
        return {
            "body": b"%PDF-1.4 fake pdf bytes",
            "content_type": "application/pdf",
            "suggested_filename": "1-01.pdf",
        }

    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    monkeypatch.setattr(scraper_module, "_apply_playwright_session_state", fake_apply_session_state)
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_page_fetch", fake_page_fetch)
    monkeypatch.setattr(scraper_module, "_use_persistent_playwright_profile", lambda: False)

    fetched = await scraper_module._download_document_bytes_via_playwright(
        "https://apps.azsos.gov/public_services/Title_01/1-01.pdf"
    )

    assert fetched == {
        "body": b"%PDF-1.4 fake pdf bytes",
        "content_type": "application/pdf",
        "suggested_filename": "1-01.pdf",
    }
    assert fake_page.goto_calls == [
        ("https://apps.azsos.gov/public_services/CodeTOC.htm", "domcontentloaded", 30000)
    ]
    assert page_fetch_calls == [
        (fake_page, "https://apps.azsos.gov/public_services/Title_01/1-01.pdf")
    ]


@pytest.mark.asyncio
async def test_download_document_bytes_via_playwright_retries_without_persistent_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def __init__(self, name: str):
            self.name = name
            self.goto_calls = []

        async def goto(self, url, wait_until=None, timeout=None):
            self.goto_calls.append((url, wait_until, timeout))

    class FakeContext:
        def __init__(self, page):
            self._page = page
            self.pages = []

        async def new_page(self):
            return self._page

        async def close(self):
            return None

        async def add_cookies(self, cookies):
            return None

    class FakeBrowser:
        def __init__(self, context):
            self._context = context

        async def new_context(self, **kwargs):
            return self._context

        async def close(self):
            return None

    class FakeChromium:
        def __init__(self, persistent_context, browser):
            self._persistent_context = persistent_context
            self._browser = browser

        async def launch_persistent_context(self, **kwargs):
            return self._persistent_context

        async def launch(self, **kwargs):
            return self._browser

    class FakePlaywright:
        def __init__(self, persistent_context, browser):
            self.chromium = FakeChromium(persistent_context, browser)

    class FakePlaywrightManager:
        def __init__(self, persistent_context, browser):
            self._playwright = FakePlaywright(persistent_context, browser)

        async def __aenter__(self):
            return self._playwright

        async def __aexit__(self, exc_type, exc, tb):
            return False

    persistent_page = FakePage("persistent")
    fallback_page = FakePage("fallback")
    persistent_context = FakeContext(persistent_page)
    fallback_context = FakeContext(fallback_page)
    fallback_browser = FakeBrowser(fallback_context)
    fake_async_api = SimpleNamespace(
        async_playwright=lambda: FakePlaywrightManager(persistent_context, fallback_browser)
    )
    page_fetch_calls = []

    async def fake_apply_session_state(context, page, url):
        return None

    async def fake_page_fetch(page, url):
        page_fetch_calls.append(page.name)
        if page.name == "persistent":
            return None
        return {
            "body": b"{\\rtf1\\ansi fallback bytes}",
            "content_type": "application/rtf",
            "suggested_filename": "1-01.rtf",
        }

    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    monkeypatch.setattr(scraper_module, "_apply_playwright_session_state", fake_apply_session_state)
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_page_fetch", fake_page_fetch)
    monkeypatch.setattr(scraper_module, "_use_persistent_playwright_profile", lambda: True)

    fetched = await scraper_module._download_document_bytes_via_playwright(
        "https://apps.azsos.gov/public_services/Title_01/1-01.rtf"
    )

    assert fetched == {
        "body": b"{\\rtf1\\ansi fallback bytes}",
        "content_type": "application/rtf",
        "suggested_filename": "1-01.rtf",
    }
    assert page_fetch_calls == ["persistent", "persistent", "fallback"]
    assert persistent_page.goto_calls == [
        ("https://apps.azsos.gov/public_services/CodeTOC.htm", "domcontentloaded", 30000)
    ]
    assert fallback_page.goto_calls == [
        ("https://apps.azsos.gov/public_services/CodeTOC.htm", "domcontentloaded", 30000)
    ]


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
    monkeypatch.setattr(scraper_module, "_download_document_bytes_via_cloudscraper", lambda url: None)
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


@pytest.mark.asyncio
async def test_scrape_wyoming_rule_detail_via_ajax_uses_rule_version_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, *, status_code=200, headers=None, text=""):
            self.status_code = status_code
            self.headers = headers or {"content-type": "text/html; charset=utf-8"}
            self.text = text

    observed: dict[str, object] = {}

    def fake_post(url, data=None, timeout=0, headers=None):
        observed["url"] = url
        observed["data"] = data
        observed["headers"] = headers
        return FakeResponse(
            text=(
                '<div class="rule_viewer_agency">Accountants, Board of Certified Public</div>'
                '<div class="rule_viewer_chapter">Chapter 1: General Provisions</div>'
                '<div id="rule_viewer_html">'
                '<p>Section 1. Authority.</p><p>The Wyoming Board hereby adopts these rules pursuant to W.S. 16-3-103.</p>'
                '<p>Section 2. Definitions.</p><p>Definitions apply throughout this chapter.</p>'
                '</div>'
            )
        )

    monkeypatch.setattr(scraper_module.requests, "post", fake_post)

    scraped = await scraper_module._scrape_wyoming_rule_detail_via_ajax(
        "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225"
    )

    assert observed["url"] == "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML"
    assert observed["data"] == {"RULE_VERSION_ID": "16225"}
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert headers.get("X-Requested-With") == "XMLHttpRequest"
    assert scraped is not None
    assert scraped.method_used == "wyoming_rules_ajax_viewer"
    assert scraped.title == "Chapter 1: General Provisions - Accountants, Board of Certified Public"
    assert "Section 1. Authority." in scraped.text
    assert scraper_module._is_substantive_rule_text(
        text=scraped.text,
        title=scraped.title,
        url="https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225",
        min_chars=300,
    ) is True


@pytest.mark.asyncio
async def test_scrape_south_dakota_rule_detail_via_api_uses_rule_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, *, status_code=200, json_data=None):
            self.status_code = status_code
            self._json_data = json_data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise scraper_module.requests.HTTPError(f"status {self.status_code}")

        def json(self):
            return self._json_data

    observed: list[str] = []

    def fake_get(url, timeout=0, headers=None, params=None):
        observed.append(url)
        assert params is None
        return FakeResponse(
            json_data={
                "RuleNumber": "20:48:03:01",
                "Catchline": "Application for licensure by examination.",
                "Html": (
                    "<html><body><p align='center'><b>20:48:03:01</b></p>"
                    "<p><b>Application for licensure by examination.</b></p>"
                    "<p>An applicant shall submit the required application and fee to the board.</p>"
                    "<p>The board may require supporting documentation and verification.</p></body></html>"
                ),
            }
        )

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    scraped = await scraper_module._scrape_south_dakota_rule_detail_via_api(
        "https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx?Rule=20:48:03:01"
    )

    assert observed == ["https://sdlegislature.gov/api/Rules/20:48:03:01"]
    assert scraped is not None
    assert scraped.method_used == "south_dakota_rules_api"
    assert scraped.title == "20:48:03:01 Application for licensure by examination."
    assert "An applicant shall submit the required application and fee to the board." in scraped.text


@pytest.mark.asyncio
async def test_discover_south_dakota_rule_document_urls_uses_rules_list_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(self, *, status_code=200, json_data=None):
            self.status_code = status_code
            self._json_data = json_data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise scraper_module.requests.HTTPError(f"status {self.status_code}")

        def json(self):
            return self._json_data

    observed: list[str] = []

    def fake_get(url, timeout=0, headers=None):
        observed.append(url)
        if url == "https://sdlegislature.gov/api/Rules":
            return FakeResponse(
                json_data=[
                    {"RuleNumber": "01:15", "Status": "Active", "Catchline": "TELECOMMUNICATIONS NETWORK"},
                    {"RuleNumber": "02:05", "Status": "Active", "Catchline": "TRAINING AND CERTIFICATION FOR LAW ENFORCEMENT OFFICERS"},
                    {"RuleNumber": "02:02", "Status": "Transferred", "Catchline": "BUREAU OF CRIMINAL STATISTICS"},
                ]
            )
        if url == "https://sdlegislature.gov/api/Rules/01:15":
            return FakeResponse(json_data={"Html": "<div>No child rules</div>"})
        if url == "https://sdlegislature.gov/api/Rules/02:05":
            return FakeResponse(
                json_data={
                    "Html": (
                        '<a href="/Rules/Administrative/DisplayRule.aspx?Rule=02:05:01">Rule 1</a>'
                        '<a href="/Rules/Administrative/DisplayRule.aspx?Rule=02:05:02">Rule 2</a>'
                    )
                }
            )
        return FakeResponse(
            status_code=404,
            json_data={}
        )

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    urls = await scraper_module._discover_south_dakota_rule_document_urls(limit=2)

    assert observed == [
        "https://sdlegislature.gov/api/Rules",
        "https://sdlegislature.gov/api/Rules/01:15",
        "https://sdlegislature.gov/api/Rules/02:05",
    ]
    assert urls == [
        "https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx?Rule=02:05:01",
        "https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx?Rule=02:05:02",
    ]


def test_accepts_new_hampshire_archived_rule_chapter() -> None:
    statute = {
        "code_name": "New Hampshire Administrative Rules (Agentic Discovery)",
        "section_name": "Agr 500",
        "source_url": "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr500.html",
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


def test_accepts_new_hampshire_archived_rule_chapter_as_substantive_rule_text() -> None:
    text = (
        "He-P 300 Communic. Diseas 4 captures 03 Jun 2025 - 11 Jan 2026 "
        "CHAPTER He-P 300 DISEASES Statutory Authority: RSA 141-C:6 "
        "PART He-P 301 COMMUNICABLE DISEASES "
        "He-P 301.01 Definitions. "
        '(a) "Acceptable immunization" means the immunizations required in RSA 141-C:20-a and the doses and age requirements in He-P 301.14. '
        '(b) "Admitting official" means the principal or his or her designated representative, headmaster or director of the public or non-public school, state agency, or child care agency. '
        '(c) "Applicant" means the person for whom application is made to either the AIDS drug assistance or the tuberculosis patient care financial assistance program. '
        '(d) "Carrier" means a person or animal that harbors a specific infectious agent in the absence of discernible clinical disease and serves as a potential source of infection. '
        '(e) "Case" means any person afflicted with a communicable disease. '
        '(f) "Chief complaint" means the patient\'s set of symptoms and illnesses when the patient first presents to the emergency department of a hospital.'
    )

    assert _is_substantive_rule_text(
        text=text,
        title="He-P 300 Communic. Diseas",
        url="https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html",
        min_chars=220,
    ) is True


def test_rejects_texas_transfer_page_as_substantive_admin_rule() -> None:
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
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_accepts_texas_appian_summary_rule_body_as_substantive_admin_rule() -> None:
    statute = {
        "code_name": "Texas Administrative Rules (Agentic Discovery)",
        "section_name": "Rule §3.5 Submission Process",
        "source_url": (
            "https://texas-sos.appianportalsgov.com/rules-and-meetings?recordId=204852"
            "&queryAsDate=03/14/2026&interface=VIEW_TAC_SUMMARY&$locale=en_US"
        ),
        "full_text": (
            "Rule §3.5 Submission Process. "
            "(a) When applying for a grant pursuant to a RFA published by the PSO in either eGrants or the Texas Register, "
            "applicants must submit and certify their grant applications in eGrants. "
            "(b) The PSO may require additional supporting documents, certifications, and budget detail forms as part of the application process. "
            "(c) Applications that do not comply with submission requirements may be denied without further review."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=220) is True


def test_score_candidate_url_prioritizes_texas_appian_rule_pages_over_transfer_notices() -> None:
    inventory_url = "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC&title=1"
    detail_url = (
        "https://texas-sos.appianportalsgov.com/rules-and-meetings?recordId=204859&queryAsDate=03/14/2026"
        "&interface=VIEW_TAC_SUMMARY&$locale=en_US"
    )
    transfer_url = "https://www.sos.state.tx.us/texreg/transfers/aging091004.html"

    assert scraper_module._score_candidate_url(detail_url) > scraper_module._score_candidate_url(inventory_url)
    assert scraper_module._score_candidate_url(inventory_url) > scraper_module._score_candidate_url(transfer_url)


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


def test_rejects_illinois_jcar_admin_index_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Illinois Administrative Rules (Agentic Discovery)",
        "section_name": "Illinois General Assembly - ADMINISTRATIVE CODE",
        "source_url": "https://www.ilga.gov/agencies/JCAR/AdminCode",
        "full_text": (
            "Illinois Administrative Code Disclaimer TITLE 1 GENERAL PROVISIONS TITLE 2 GOVERNMENTAL ORGANIZATION "
            "TITLE 3 LEGISLATURE TITLE 4 DISCRIMINATION PROCEDURES TITLE 8 AGRICULTURE AND ANIMALS TITLE 11 ALCOHOL, HORSE RACING, LOTTERY, AND VIDEO GAMING "
            "TITLE 14 COMMERCE TITLE 17 CONSERVATION TITLE 20 CORRECTIONS, CRIMINAL JUSTICE, AND LAW ENFORCEMENT TITLE 23 EDUCATION AND CULTURAL RESOURCES."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert scraper_module._looks_like_rule_inventory_page(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_rejects_illinois_jcar_sections_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Illinois Administrative Rules (Agentic Discovery)",
        "section_name": "Illinois General Assembly - ADMINISTRATIVE CODE",
        "source_url": "https://www.ilga.gov/agencies/JCAR/Sections?PartID=00100100&TitleDescription=TITLE%201:%20%20GENERAL%20PROVISIONS",
        "full_text": (
            "TITLE 1 GENERAL PROVISIONS CHAPTER I SECRETARY OF STATE PART 100 RULEMAKING IN ILLINOIS View Entire Part "
            "Section 100.100 Rulemaking Compliance Section 100.110 Definitions Section 100.120 Agencies Covered "
            "Section 100.130 Illinois Administrative Code Organization Section 100.140 Codification Outline Section 100.150 Notice of Codification Changes "
            "Section 100.160 Deletion or Transfer of Rules Section 100.170 Re-using Part or Section Numbers."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert scraper_module._looks_like_rule_inventory_page(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is True


def test_accepts_illinois_jcar_static_section_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Illinois Administrative Rules (Agentic Discovery)",
        "section_name": "Section 100.100 Rulemaking Compliance",
        "source_url": "https://www.ilga.gov/commission/jcar/admincode/001/001001000A01000R.html",
        "full_text": (
            "TITLE 1 GENERAL PROVISIONS CHAPTER I SECRETARY OF STATE PART 100 RULEMAKING IN ILLINOIS SECTION 100.100 RULEMAKING COMPLIANCE. "
            "This Part describes the procedures involved in promulgating rules in codified form, including both Illinois Register publication and filing requirements. "
            "All rules filed with the Index Department must be in compliance with the rulemaking system described within this Part pursuant to Article 5 of the Illinois Administrative Procedure Act. "
            "Source: Amended at 18 Ill. Reg. 13067, effective August 11, 1994."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is True


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


def test_accepts_indiana_procurement_article_detail_page_despite_policy_terms() -> None:
    statute = {
        "code_name": "Indiana Administrative Rules (Agentic Discovery)",
        "section_name": "Title 25, Article 1.1",
        "short_title": "Title 25, Article 1.1",
        "source_url": "https://iar.iga.in.gov/code/current/25/1.1",
        "full_text": (
            "25 IAC 1.1-1-1 Definitions "
            "Authority: IC 4-13-1.3-4 Affected: IC 5-22-2 "
            "Sec. 1. The requirements of IC 5-22 do not apply to employment agreements. "
            "25 IAC 1.1-1-2 Competitive sealed bids; bid guarantee "
            "Sec. 2. At the discretion of the department, bidders may be required to submit a bid guarantee. "
            "The invitation to bid may also describe the request for proposals process and contract award requirements."
        ),
        "legal_area": "administrative",
        "official_cite": "IN Admin Rule A2",
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=100) is True


def test_rejects_vermont_proposed_rule_detail_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Vermont Administrative Rules (Agentic Discovery)",
        "section_name": "Vermont Secretary of State Rules Service",
        "source_url": "https://secure.vermont.gov/SOS/rules/display.php?r=1049",
        "full_text": (
            "Vermont Secretary of State Rules Service Proposed Rules Postings A Service of the Office of the Secretary of State "
            "Code of Vermont Rules Search Rules Rule Details Rule Number: 25P039 Title: Example Rule Type: Proposed Rule "
            "Status: Proposed Agency: Agency of Administration Legal Authority: 3 V.S.A. section 845 Summary: Example summary text. "
            "Persons Affected: Agencies and members of the public. Economic Impact: Minimal. Posting date: Mar 04, 2026 "
            "Hearing Information Information for Hearing # 1 Contact Information Information for Contact # 1."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_vermont_rules_service_shell_without_rule_details() -> None:
    statute = {
        "code_name": "Vermont Administrative Rules (Agentic Discovery)",
        "section_name": "Vermont Secretary of State Rules Service",
        "source_url": "https://secure.vermont.gov/SOS/rules/display.php?r=1049",
        "full_text": (
            "Vermont Secretary of State Rules Service Proposed Rules Postings A Service of the Office of the Secretary of State "
            "Code of Vermont Rules Search Rules Deadline For Public Comment Deadline: May 08, 2026 Posting date: Mar 04, 2026 "
            "Hearing Information Information for Hearing # 1 Contact Information Information for Contact # 1."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_vermont_rules_root_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Vermont Administrative Rules (Agentic Discovery)",
        "section_name": "Vermont Secretary of State Rules Service",
        "source_url": "https://secure.vermont.gov/SOS/rules/",
        "full_text": (
            "Vermont Secretary of State Rules Service Proposed Rules Postings A Service of the Office of the Secretary of State "
            "Code of Vermont Rules Recent Search Rules Calendar Subscribe APA Contact Info Proposed State Rules Recent Postings."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_raw_html_payload_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Vermont Administrative Rules (Agentic Discovery)",
        "section_name": "<!DOCTYPE html>",
        "source_url": "https://aoa.vermont.gov/ICAR",
        "full_text": "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/><script>window.dataLayer = [];</script></head><body><div>ICAR</div></body></html>",
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_rejects_vermont_icar_service_page_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Vermont Administrative Rules (Agentic Discovery)",
        "section_name": "ICAR | Agency of Administration",
        "source_url": "https://aoa.vermont.gov/ICAR",
        "full_text": (
            "Skip to main content An Official Vermont Government Website State of Vermont Agency of Administration "
            "Administrative Bulletins Revenue Report Fiscal Transparency Strategic Plan Workers' Compensation Public Information "
            "Home About the Agency Administrative Bulletins Boards and Commissions Interagency Committee on Administrative Rules."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_vermont_lexis_sign_in_shell_as_substantive_rule_text() -> None:
    statute = {
        "code_name": "Vermont Administrative Rules (Agentic Discovery)",
        "section_name": "Lexis Sign In",
        "source_url": "https://advance.lexis.com/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00008-00",
        "full_text": (
            "Lexis - Sign In | LexisNexis Sign in to continue accessing this document. "
            "We use CAPTCHA on this site to prevent automated software from overburdening the system."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False
    assert _is_relaxed_recovery_text(
        text=statute["full_text"],
        title=statute["section_name"],
        url=statute["source_url"],
    ) is False


def test_should_abort_vermont_after_lexis_block_only_for_empty_vt_recovery() -> None:
    assert (
        scraper_module._should_abort_vermont_after_lexis_block(
            state_code="VT",
            vermont_lexis_access_blocked=True,
            statutes_count=0,
        )
        is True
    )
    assert (
        scraper_module._should_abort_vermont_after_lexis_block(
            state_code="VT",
            vermont_lexis_access_blocked=False,
            statutes_count=0,
        )
        is False
    )
    assert (
        scraper_module._should_abort_vermont_after_lexis_block(
            state_code="VT",
            vermont_lexis_access_blocked=True,
            statutes_count=1,
        )
        is False
    )
    assert (
        scraper_module._should_abort_vermont_after_lexis_block(
            state_code="TX",
            vermont_lexis_access_blocked=True,
            statutes_count=0,
        )
        is False
    )


def test_rejects_oklahoma_legislature_placeholder_as_substantive_admin_rule() -> None:
    statute = {
        "code_name": "Oklahoma Administrative Rules (Agentic Discovery)",
        "section_name": "State Legislatures, State Laws, and State Regulations: Websites / Telephone Numbers",
        "source_url": "https://legislature.ok.gov/regulations",
        "full_text": (
            "Member Login Law Librarians' Society of Washington, D.C. Legislative Source Book "
            "State Legislatures, State Laws, and State Regulations: Website Links and Telephone Numbers. "
            "Oklahoma State Legislature, Oklahoma Statutes - Search, OK Admn. Code & Register."
        ),
    }

    assert _is_admin_rule_statute(statute) is True
    assert _is_substantive_admin_statute(statute, min_chars=160) is False


def test_rejects_oklahoma_rules_portal_shell_for_section_url() -> None:
    shell_text = (
        "Skip to Main Content HOME CODE REGISTER NEWS QUICKLINKS PROPOSED RULES USER OPTIONS "
        "OKLAHOMA ADMINISTRATIVE CODE Administrative Code Search CLEAR SEARCH Search Code: Emergency Rules "
        "Title 1. Executive Orders Title 5. Oklahoma Abstractors Board Title 10. Oklahoma Accountancy Board "
        "Title 15. State Accrediting Agency Title 20. Ad Valorem Task Force Title 25. Oklahoma Department of Aerospace and Aeronautics "
        "Title 30. Board of Regents for the Oklahoma Agricultural and Mechanical Colleges Title 35. Oklahoma Department of Agriculture, Food, and Forestry"
    )

    assert (
        scraper_module._looks_like_non_rule_admin_page(
            text=shell_text,
            title="Oklahoma Rules",
            url="https://rules.ok.gov/code?titleNum=5&sectionNum=5%3A2-1-1",
        )
        is True
    )


def test_accepts_oklahoma_rules_api_section_text_as_substantive_rule_text() -> None:
    rule_text = (
        "In addition to the terms defined in the Oklahoma Abstractors Act, the definitions of the following words and terms "
        "shall be applied when implementing the Act and rules adopted by the Board: \n"
        '"Abstractor" means the holder of an abstract license, certificate of authority, or temporary certificate of authority. \n'
        '"Act" means the Oklahoma Abstractors Act. \n'
        '"Board" means the Oklahoma Abstractors Board. \n'
        '"Certificate of authority" means the authority granted by the Board to own and operate an abstract business in Oklahoma.'
    )

    assert _is_substantive_rule_text(
        text=rule_text,
        title="5:2-1-2 Definitions",
        url="https://rules.ok.gov/code?titleNum=5&sectionNum=5%3A2-1-2",
        min_chars=300,
    ) is True


def test_vermont_lexis_toc_counts_as_inventory_not_substantive_detail() -> None:
    toc_text = (
        "Vermont Statutes, Court Rules and Administrative Code Public Access Code of Vermont Rules PAW - ET Table of Contents "
        "AGENCY 01. GOVERNOR AGENCY 10. AGENCY OF ADMINISTRATION AGENCY 13. AGENCY OF HUMAN SERVICES"
    )

    assert scraper_module._looks_like_rule_inventory_page(
        text=toc_text,
        title="Vermont Statutes, Court Rules and Administrative Code Public Access | Code Main Page",
        url="https://www.lexisnexis.com/hottopics/codeofvtrules/",
    ) is True


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


def test_candidate_utah_rule_urls_from_public_api_caps_broad_bootstrap_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "programs": [
                {
                    "rules": [
                        {
                            "referenceNumber": f"R70-10{index}",
                            "linkToRule": f"R70-10{index}/Current Rules",
                        }
                        for index in range(12)
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

    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: _FakeResponse())

    urls = _candidate_utah_rule_urls_from_public_api(
        url="https://adminrules.utah.gov/public/search//Current%20Rules",
        limit=24,
    )

    assert len(urls) == 8
    assert urls[0] == "https://adminrules.utah.gov/public/rule/R70-100/Current%20Rules"
    assert urls[-1] == "https://adminrules.utah.gov/public/rule/R70-107/Current%20Rules"


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


def test_score_candidate_url_prioritizes_indiana_iar_pages_over_dead_legislature_pages() -> None:
    inventory_score = scraper_module._score_candidate_url(
        "https://iar.iga.in.gov/code/current"
    )
    detail_score = scraper_module._score_candidate_url(
        "https://iar.iga.in.gov/code/current/25/1.5"
    )
    dead_legislature_score = scraper_module._score_candidate_url(
        "https://legislature.in.gov/regulations"
    )

    assert inventory_score > dead_legislature_score
    assert detail_score > inventory_score


def test_score_candidate_url_prioritizes_alabama_admin_code_detail_pages() -> None:
    detail_score = scraper_module._score_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code"
    )
    query_detail_score = scraper_module._score_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01"
    )
    anchor_score = scraper_module._score_candidate_url(
        "https://admincode.legislature.state.al.us/administrative-code#A"
    )
    search_score = scraper_module._score_candidate_url(
        "https://admincode.legislature.state.al.us/search"
    )
    agency_score = scraper_module._score_candidate_url(
        "https://admincode.legislature.state.al.us/agency"
    )

    assert detail_score > search_score
    assert query_detail_score > detail_score
    assert anchor_score > search_score
    assert detail_score > agency_score


def test_score_candidate_url_prioritizes_new_hampshire_archived_rule_chapters() -> None:
    archived_detail_score = scraper_module._score_candidate_url(
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr100.html"
    )
    archived_inventory_score = scraper_module._score_candidate_url(
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx"
    )
    live_template_score = scraper_module._score_candidate_url(
        "https://legislature.nh.gov/regulations"
    )

    assert archived_detail_score > archived_inventory_score
    assert archived_detail_score > live_template_score
    assert archived_inventory_score > live_template_score


def test_score_candidate_url_prioritizes_vermont_rule_display_pages() -> None:
    lexis_doc_score = scraper_module._score_candidate_url(
        "https://advance.lexis.com/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00008-00"
    )
    proposal_score = scraper_module._score_candidate_url(
        "https://secure.vermont.gov/SOS/rules/display.php?r=1049"
    )
    inventory_score = scraper_module._score_candidate_url(
        "https://secure.vermont.gov/SOS/rules/"
    )
    search_score = scraper_module._score_candidate_url(
        "https://secure.vermont.gov/SOS/rules/search.php"
    )
    legislature_score = scraper_module._score_candidate_url(
        "https://legislature.vt.gov/regulations"
    )

    assert inventory_score > proposal_score
    assert inventory_score > search_score
    assert inventory_score > legislature_score


def test_vermont_proposal_display_page_is_not_rule_detail_page() -> None:
    text = (
        "Proposed Rules Postings A Service of the Office of the Secretary of State "
        "Code of Vermont Rules Search Rules Deadline For Public Comment Deadline: May 08, 2026 "
        "Rule Details Rule Number: 26P006 Title: Estate Recovery Type: Standard Status: Proposed "
        "Agency: Agency of Human Services Legal Authority: 3 V.S.A. section 801(b)(11)."
    )

    assert scraper_module._is_vermont_rule_detail_page(
        text=text,
        title="Vermont Secretary of State Rules Service",
        url="https://secure.vermont.gov/SOS/rules/display.php?r=1049",
    ) is False


@pytest.mark.anyio
async def test_agentic_discovery_does_not_bootstrap_vermont_lexis_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://secure.vermont.gov/SOS/rules/"
    called = False

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
                text="Vermont Secretary of State Rules Service Code of Vermont Rules Recent Search Rules Calendar",
                title="Vermont Secretary of State Rules Service",
                html="<form><input name='r' value='1049'></form>",
                extraction_provenance={"method": "beautifulsoup"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(
                text="Vermont Secretary of State Rules Service Code of Vermont Rules Recent Search Rules Calendar",
                title="Vermont Secretary of State Rules Service",
                html="<form><input name='r' value='1049'></form>",
                links=[],
            )

    async def _fake_discover_vermont_lexis_document_urls(*, seed_urls: list[str], limit: int = 8) -> list[str]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_discover_vermont_lexis_document_urls", _fake_discover_vermont_lexis_document_urls)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
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
        states=["VT"],
        max_candidates_per_state=4,
        max_fetch_per_state=2,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=160,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 0
    assert called is False


def test_score_candidate_url_prioritizes_oklahoma_rules_api_sections_over_legislature_placeholders() -> None:
    detail_url = "https://rules.ok.gov/code?titleNum=10&sectionNum=10%3A1-1-1"
    inventory_url = "https://rules.ok.gov/code"
    placeholder_url = "https://legislature.ok.gov/regulations"

    assert scraper_module._score_candidate_url(detail_url) > scraper_module._score_candidate_url(inventory_url)
    assert scraper_module._score_candidate_url(inventory_url) > scraper_module._score_candidate_url(placeholder_url)


def test_score_candidate_url_prioritizes_tennessee_sharetngov_rule_pages() -> None:
    chapter_score = scraper_module._score_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/0020/0020.htm"
    )
    flat_pdf_score = scraper_module._score_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/0020/0020-01.20170126.pdf"
    )
    nested_chapter_score = scraper_module._score_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/1200/1200-13/1200-13.htm"
    )
    nested_pdf_score = scraper_module._score_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/1200/1200-13/1200-13-14.20150930.pdf"
    )
    tar_index_score = scraper_module._score_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/pub/tar/index.htm"
    )
    effective_rules_score = scraper_module._score_candidate_url(
        "https://sharetngov.tnsosfiles.com/sos/rules/rules2.htm"
    )
    sos_service_score = scraper_module._score_candidate_url(
        "https://sos.tn.gov/publications/services/administrative-register"
    )
    tn_gov_404_score = scraper_module._score_candidate_url(
        "https://www.tn.gov/sos/rules-and-regulations.html"
    )
    legislature_score = scraper_module._score_candidate_url(
        "https://legislature.tn.gov/regulations"
    )

    assert chapter_score > tar_index_score
    assert flat_pdf_score > tar_index_score
    assert nested_chapter_score > tar_index_score
    assert nested_pdf_score > tar_index_score
    assert tar_index_score > sos_service_score
    assert effective_rules_score > sos_service_score
    assert sos_service_score > tn_gov_404_score
    assert chapter_score > legislature_score
    assert effective_rules_score > legislature_score
    assert tar_index_score > legislature_score


def test_score_candidate_url_prioritizes_south_dakota_rule_pages_over_index() -> None:
    section_score = scraper_module._score_candidate_url(
        "https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx?Rule=20:48:03:01"
    )
    chapter_score = scraper_module._score_candidate_url(
        "https://sdlegislature.gov/Rules/Administrative/01:15"
    )
    index_score = scraper_module._score_candidate_url(
        "https://sdlegislature.gov/Rules/Administrative"
    )
    root_score = scraper_module._score_candidate_url("https://rules.sd.gov/")

    assert section_score > chapter_score
    assert chapter_score > index_score
    assert index_score >= root_score


def test_prefers_live_fetch_for_utah_detail_pages() -> None:
    assert (
        scraper_module._prefers_live_fetch(
            "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules"
        )
        is True
    )
    assert scraper_module._prefers_live_fetch("https://rules.utah.gov/") is False


def test_prefers_live_fetch_for_tennessee_inventory_pages() -> None:
    assert scraper_module._prefers_live_fetch("https://sharetngov.tnsosfiles.com/sos/rules/rules2.htm") is True
    assert scraper_module._prefers_live_fetch("https://sharetngov.tnsosfiles.com/sos/rules/effectives/effectives.htm") is True
    assert scraper_module._prefers_live_fetch("https://sharetngov.tnsosfiles.com/sos/rules/0020/0020.htm") is False


def test_prefers_live_fetch_for_texas_appian_tac_pages() -> None:
    assert (
        scraper_module._prefers_live_fetch(
            "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC&title=1"
        )
        is True
    )
    assert (
        scraper_module._prefers_live_fetch(
            "https://texas-sos.appianportalsgov.com/rules-and-meetings?recordId=204859&queryAsDate=03/14/2026&interface=VIEW_TAC_SUMMARY&$locale=en_US"
        )
        is True
    )
    assert scraper_module._prefers_live_fetch("https://www.sos.state.tx.us/texreg/transfers/aging091004.html") is False


def test_prefers_live_fetch_for_vermont_lexis_sources() -> None:
    assert scraper_module._prefers_live_fetch("https://www.lexisnexis.com/hottopics/codeofvtrules/") is True
    assert (
        scraper_module._prefers_live_fetch(
            "https://advance.lexis.com/shared/document/administrative-codes/urn:contentItem:5WS0-FPD1-FGRY-B08T-00008-00"
        )
        is False
    )


def test_prefers_live_fetch_for_oklahoma_rules_code_pages() -> None:
    assert scraper_module._prefers_live_fetch("https://rules.ok.gov/code?titleNum=10&sectionNum=10%3A1-1-1") is True
    assert scraper_module._prefers_live_fetch("https://rules.ok.gov/code") is False


def test_candidate_oklahoma_rule_urls_from_text_extracts_title_urls() -> None:
    text = (
        "Oklahoma Administrative Code Administrative Code Search Title 1. Executive Orders "
        "Title 5. Oklahoma Abstractors Board Title 10. Oklahoma Accountancy Board "
        "Title 15. State Accrediting Agency (abolished 7-1-19) Title 25. Oklahoma Department of Aerospace and Aeronautics"
    )

    assert scraper_module._candidate_oklahoma_rule_urls_from_text(
        text=text,
        page_url="https://rules.ok.gov/code",
        limit=8,
    ) == [
        "https://rules.ok.gov/code?titleNum=1",
        "https://rules.ok.gov/code?titleNum=5",
        "https://rules.ok.gov/code?titleNum=10",
        "https://rules.ok.gov/code?titleNum=25",
    ]


@pytest.mark.asyncio
async def test_scrape_oklahoma_rule_detail_via_api_extracts_section_text(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper_module._OKLAHOMA_TITLE_SEGMENTS_CACHE.clear()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [
                {
                    "sectionNum": "10:1-1-1",
                    "description": "Purpose",
                    "text": "<div>(a) The Oklahoma Accountancy Act protects the public.</div>",
                }
            ]

    def fake_get(url, params=None, timeout=0, headers=None):
        assert url == "https://okadminrules-api.azurewebsites.net/GetSegmentsByTitleNum"
        assert (params or {}).get("titleNum") == "10"
        return FakeResponse()

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    scraped = await scraper_module._scrape_oklahoma_rule_detail_via_api(
        "https://rules.ok.gov/code?titleNum=10&sectionNum=10%3A1-1-1"
    )

    assert scraped is not None
    assert scraped.title == "10:1-1-1 Purpose"
    assert "The Oklahoma Accountancy Act protects the public." in scraped.text
    assert scraped.method_used == "oklahoma_rules_api"


@pytest.mark.asyncio
async def test_discover_oklahoma_rule_document_urls_prefers_longer_section_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper_module._OKLAHOMA_TITLE_SEGMENTS_CACHE.clear()

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_get(url, params=None, timeout=0, headers=None):
        if url == "https://okadminrules-api.azurewebsites.net/GetAllRules":
            return FakeResponse([
                {"referenceCode": "5"},
            ])
        assert url == "https://okadminrules-api.azurewebsites.net/GetSegmentsByTitleNum"
        assert (params or {}).get("titleNum") == "5"
        return FakeResponse([
            {
                "name": "Section",
                "sectionNum": "5:2-1-1",
                "text": "<div>short text</div>",
            },
            {
                "name": "Section",
                "sectionNum": "5:2-1-2",
                "text": "<div>" + ("medium text " * 20) + "</div>",
            },
            {
                "name": "Section",
                "sectionNum": "5:2-1-3",
                "text": "<div>" + ("long text " * 40) + "</div>",
            },
        ])

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    urls = await scraper_module._discover_oklahoma_rule_document_urls(limit=2)

    assert urls == [
        "https://rules.ok.gov/code?titleNum=5&sectionNum=5%3A2-1-3",
        "https://rules.ok.gov/code?titleNum=5&sectionNum=5%3A2-1-2",
    ]


@pytest.mark.asyncio
async def test_scrape_oklahoma_rule_detail_via_api_extracts_title_text_for_title_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper_module._OKLAHOMA_TITLE_SEGMENTS_CACHE.clear()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [
                {
                    "name": "Title",
                    "description": "Oklahoma Accountancy Board",
                    "sectionNum": None,
                    "text": None,
                },
                {
                    "name": "Section",
                    "sectionNum": "10:1-1-1",
                    "description": "Purpose",
                    "text": "<div>(a) The Oklahoma Accountancy Act protects the public.</div>",
                },
                {
                    "name": "Section",
                    "sectionNum": "10:1-1-2",
                    "description": "Definitions",
                    "text": "<div>(b) Terms used in this chapter have the following meanings.</div>",
                },
            ]

    monkeypatch.setattr(scraper_module.requests, "get", lambda *args, **kwargs: FakeResponse())

    scraped = await scraper_module._scrape_oklahoma_rule_detail_via_api(
        "https://rules.ok.gov/code?titleNum=10"
    )

    assert scraped is not None
    assert scraped.title == "Title 10 Oklahoma Accountancy Board"
    assert "10:1-1-1 Purpose" in scraped.text
    assert "10:1-1-2 Definitions" in scraped.text
    assert scraped.method_used == "oklahoma_rules_api"


@pytest.mark.asyncio
async def test_scrape_oklahoma_rule_detail_via_api_reuses_cached_title_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper_module._OKLAHOMA_TITLE_SEGMENTS_CACHE.clear()
    request_calls: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [
                {
                    "name": "Title",
                    "description": "Oklahoma Abstractors Board",
                    "sectionNum": None,
                    "text": None,
                },
                {
                    "name": "Section",
                    "sectionNum": "5:2-1-3",
                    "description": "Authority, interpretation, and severability of rules",
                    "text": "<div>(a) Rule text one.</div>",
                },
                {
                    "name": "Section",
                    "sectionNum": "5:2-3-4",
                    "description": "Availability of records; copies",
                    "text": "<div>(b) Rule text two.</div>",
                },
            ]

    def fake_get(url, params=None, timeout=0, headers=None):
        request_calls.append({"url": url, "params": params, "timeout": timeout})
        assert url == "https://okadminrules-api.azurewebsites.net/GetSegmentsByTitleNum"
        assert (params or {}).get("titleNum") == "5"
        return FakeResponse()

    monkeypatch.setattr(scraper_module.requests, "get", fake_get)

    first_scraped = await scraper_module._scrape_oklahoma_rule_detail_via_api(
        "https://rules.ok.gov/code?titleNum=5&sectionNum=5%3A2-1-3"
    )
    second_scraped = await scraper_module._scrape_oklahoma_rule_detail_via_api(
        "https://rules.ok.gov/code?titleNum=5&sectionNum=5%3A2-3-4"
    )

    assert first_scraped is not None
    assert second_scraped is not None
    assert len(request_calls) == 1
    assert "Rule text one." in first_scraped.text
    assert "Rule text two." in second_scraped.text


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
    rule_url = "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01"

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
    monkeypatch.setattr(scraper_module, "_discover_alabama_rule_document_urls", lambda limit=8: asyncio.sleep(0, result=[rule_url]))
    monkeypatch.setattr(
        scraper_module,
        "_scrape_alabama_rule_detail_via_api",
        lambda url: asyncio.sleep(
            0,
            result=SimpleNamespace(
                text="Official Alabama administrative rules body with authority and chapter text.",
                title="20-X-2-.01 Alabama Administrative Code",
                method_used="alabama_public_code_api",
            ),
        ),
    )
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
    assert result["state_blocks"][0]["statutes"][0]["source_url"] == rule_url


@pytest.mark.anyio
async def test_agentic_discovery_continues_when_archive_search_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    rule_url = "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01"

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            raise asyncio.TimeoutError()

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
    monkeypatch.setattr(scraper_module, "_discover_alabama_rule_document_urls", lambda limit=8: asyncio.sleep(0, result=[rule_url]))
    monkeypatch.setattr(
        scraper_module,
        "_scrape_alabama_rule_detail_via_api",
        lambda url: asyncio.sleep(
            0,
            result=SimpleNamespace(
                text="Official Alabama administrative rules body with authority and chapter text.",
                title="20-X-2-.01 Alabama Administrative Code",
                method_used="alabama_public_code_api",
            ),
        ),
    )
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
    assert result["report"]["AL"]["candidate_urls"] >= 1
    assert result["report"]["AL"]["fetched_rules"] == 1
    assert result["report"]["AL"]["timed_out"] is False


@pytest.mark.anyio
async def test_agentic_discovery_bootstraps_alabama_public_code_before_broad_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_url = "https://admincode.legislature.state.al.us/administrative-code?number=20-X-2-.01"
    archive_calls = 0
    unified_search_calls = 0
    agentic_calls = 0

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            nonlocal archive_calls
            archive_calls += 1
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            nonlocal unified_search_calls
            unified_search_calls += 1
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            nonlocal agentic_calls
            agentic_calls += 1
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(text="", title="", html="", extraction_provenance={"method": "requests_only"})
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

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: ["https://admincode.legislature.state.al.us/administrative-code"])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_discover_alabama_rule_document_urls", lambda limit=8: asyncio.sleep(0, result=[rule_url]))
    monkeypatch.setattr(
        scraper_module,
        "_scrape_alabama_rule_detail_via_api",
        lambda url: asyncio.sleep(
            0,
            result=SimpleNamespace(
                text="Official Alabama administrative rules body with authority and chapter text.",
                title="20-X-2-.01 Alabama Administrative Code",
                method_used="alabama_public_code_api",
                extraction_provenance={"method": "alabama_public_code_api"},
            ),
        ),
    )
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
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
    assert result["report"]["AL"]["fetched_rules"] == 1
    assert result["report"]["AL"]["source_breakdown"]["alabama_public_code_bootstrap"] == 1
    assert result["report"]["AL"]["timed_out"] is False
    assert archive_calls == 0
    assert unified_search_calls == 0
    assert agentic_calls == 0


@pytest.mark.anyio
async def test_agentic_discovery_bootstraps_south_dakota_rules_api_before_broad_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_url = "https://sdlegislature.gov/Rules/Administrative/20:48:03:01"
    archive_calls = 0
    unified_search_calls = 0
    agentic_calls = 0

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            nonlocal archive_calls
            archive_calls += 1
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            nonlocal unified_search_calls
            unified_search_calls += 1
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            nonlocal agentic_calls
            agentic_calls += 1
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(text="", title="", html="", extraction_provenance={"method": "requests_only"})
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

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(
        scraper_module,
        "_extract_seed_urls_for_state",
        lambda state_code, state_name: ["https://sdlegislature.gov/Rules/Administrative"],
    )
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_discover_south_dakota_rule_document_urls", lambda limit=8: asyncio.sleep(0, result=[rule_url]))
    monkeypatch.setattr(
        scraper_module,
        "_scrape_south_dakota_rule_detail_via_api",
        lambda url: asyncio.sleep(
            0,
            result=SimpleNamespace(
                text="Official South Dakota administrative rule text with authority, scope, and procedural requirements.",
                title="20:48:03:01 Application for licensure by examination.",
                method_used="south_dakota_rules_api",
                extraction_provenance={"method": "south_dakota_rules_api"},
            ),
        ),
    )
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
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
        states=["SD"],
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
    assert result["report"]["SD"]["fetched_rules"] == 1
    assert result["report"]["SD"]["source_breakdown"]["south_dakota_rules_api_bootstrap"] == 1
    assert result["report"]["SD"]["timed_out"] is False
    assert archive_calls == 0
    assert unified_search_calls == 0
    assert agentic_calls == 0


@pytest.mark.anyio
async def test_agentic_discovery_processes_multiple_states_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_urls = {
        "AL": "https://admincode.legislature.state.al.us/administrative-code",
        "AK": "https://ltgov.alaska.gov/information/regulations/",
    }
    fetch_events: list[tuple[str, str, float]] = []

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
            url = str(getattr(request, "url", "") or "")
            fetch_events.append(("start", url, time.monotonic()))
            time.sleep(0.05)
            fetch_events.append(("end", url, time.monotonic()))
            document = SimpleNamespace(
                text=f"{url} administrative rules authority purpose chapter text.",
                title="Administrative Code",
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

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_urls[state_code]])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: True)
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
        states=["AL", "AK"],
        max_candidates_per_state=4,
        max_fetch_per_state=1,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["parallel_state_workers"] == 2
    assert [block["state_code"] for block in result["state_blocks"]] == ["AL", "AK"]
    assert all(block["rules_count"] == 1 for block in result["state_blocks"])

    starts = {url: timestamp for phase, url, timestamp in fetch_events if phase == "start"}
    ends = {url: timestamp for phase, url, timestamp in fetch_events if phase == "end"}
    assert set(starts) == set(seed_urls.values())
    assert set(ends) == set(seed_urls.values())
    assert max(starts.values()) < min(ends.values())


@pytest.mark.anyio
async def test_agentic_discovery_records_cloudflare_rate_limit_metadata_and_prefers_cloudflare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_methods: list[list[str]] = []

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
                text="",
                title="Arizona Administrative Rules",
                html="",
                extraction_provenance={
                    "method": "cloudflare_browser_rendering",
                    "cloudflare_status": "rate_limited",
                    "retry_after_seconds": 120.0,
                    "retry_at_utc": "2026-03-12T00:02:00Z",
                    "retryable": True,
                    "wait_budget_exhausted": True,
                    "rate_limit_diagnostics": {"provider": "cloudflare_browser_rendering"},
                },
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            configured_methods.append(list(getattr(cfg, "preferred_methods", []) or []))
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(text="", title="", html="", links=[])

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: ["https://rules.az.gov/"])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: False)
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
            CLOUDFLARE_BROWSER_RENDERING="cloudflare_browser_rendering",
            PLAYWRIGHT="playwright",
            BEAUTIFULSOUP="beautifulsoup",
            REQUESTS_ONLY="requests_only",
        ),
    )

    result = await _agentic_discover_admin_state_blocks(
        states=["AZ"],
        max_candidates_per_state=3,
        max_fetch_per_state=1,
        max_results_per_domain=3,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 0
    assert result["report"]["AZ"]["cloudflare_status"] == "rate_limited"
    assert result["report"]["AZ"]["retry_after_seconds"] == 120.0
    assert result["report"]["AZ"]["rate_limit_diagnostics"]["provider"] == "cloudflare_browser_rendering"
    assert any("cloudflare_browser_rendering" in methods for methods in configured_methods)


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
async def test_agentic_discovery_prefetches_arizona_seed_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    landing_url = "https://azsos.gov/rules/arizona-administrative-code"
    pdf_url = "https://apps.azsos.gov/public_services/Title_07/7-02.pdf"
    rtf_url = "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"
    pdf_calls: list[str] = []
    rtf_calls: list[str] = []
    agentic_discovery_calls = 0
    archive_search_calls = 0
    unified_search_calls = 0

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            nonlocal archive_search_calls
            archive_search_calls += 1
            return {"results": []}

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            nonlocal unified_search_calls
            unified_search_calls += 1
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            nonlocal agentic_discovery_calls
            agentic_discovery_calls += 1
            return {"results": []}

        def fetch(self, request):
            document = SimpleNamespace(
                text="Arizona Administrative Code landing page.",
                title="Arizona Administrative Code",
                html="",
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(
                text="Arizona Administrative Code landing page.",
                title="Arizona Administrative Code",
                html="",
                links=[],
            )

    async def _fake_scrape_pdf_candidate_url_with_processor(url: str):
        pdf_calls.append(url)
        if url != pdf_url:
            return None
        return SimpleNamespace(
            text="R7-2-101. Purpose. Arizona administrative code chapter text.",
            title="Title 7 Chapter 2",
            extraction_provenance={"method": "pdf_processor"},
        )

    async def _fake_scrape_rtf_candidate_url_with_processor(url: str):
        rtf_calls.append(url)
        if url != rtf_url:
            return None
        return SimpleNamespace(
            text="R18-4-101. Applicability. Arizona administrative code article text.",
            title="Title 18 Chapter 4",
            extraction_provenance={"method": "rtf_processor"},
        )

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [landing_url, pdf_url, rtf_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(
        scraper_module,
        "_scrape_pdf_candidate_url_with_processor",
        _fake_scrape_pdf_candidate_url_with_processor,
    )
    monkeypatch.setattr(
        scraper_module,
        "_scrape_rtf_candidate_url_with_processor",
        _fake_scrape_rtf_candidate_url_with_processor,
    )
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") in {pdf_url, rtf_url})
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
        states=["AZ"],
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
    assert result["state_blocks"][0]["rules_count"] == 2
    assert [statute["source_url"] for statute in result["state_blocks"][0]["statutes"]] == [rtf_url, pdf_url]
    assert pdf_calls == [pdf_url]
    assert rtf_calls == [
        rtf_url,
        "https://apps.azsos.gov/public_services/Title_07/7-02.rtf",
    ]
    assert agentic_discovery_calls == 0
    assert archive_search_calls == 0
    assert unified_search_calls == 0
    assert result["report"]["AZ"]["format_counts"]["pdf"] == 1
    assert result["report"]["AZ"]["format_counts"]["rtf"] == 1
    assert result["report"]["AZ"]["gap_summary"]["rule_hosts"] == ["azsos.gov"]


@pytest.mark.anyio
async def test_agentic_discovery_archive_prefetch_inventory_expands_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://apps.azsos.gov/public_services/CodeTOC.htm"
    inventory_url = seed_url
    pdf_url = "https://apps.azsos.gov/public_services/Title_18/18-04.pdf"
    rtf_url = "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeParallelWebArchiver:
        def __init__(self, **kwargs):
            pass

        async def archive_urls_parallel(self, urls):
            return [
                SimpleNamespace(
                    success=True,
                    url=inventory_url,
                    content=(
                        "Arizona Administrative Code. Title 1 State Government. Title 2 Administration. "
                        "Title 7 Education. Title 18 Environmental Quality. "
                        "/public_services/Title_18/18-04.pdf public_services/Title_18/18-04.rtf"
                    ),
                    source="wayback",
                )
            ]

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            return SimpleNamespace(
                document=SimpleNamespace(
                    text="Arizona Administrative Code inventory",
                    title="Arizona Administrative Code",
                    html="",
                    extraction_provenance={"method": "playwright"},
                )
            )

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(text="", title="", html="", links=[])

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: False)
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
        states=["AZ"],
        max_candidates_per_state=8,
        max_fetch_per_state=2,
        max_results_per_domain=5,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["report"]["AZ"]["expanded_urls"] >= 2
    assert result["report"]["AZ"]["parallel_prefetch"]["attempted"] >= 1
    assert seed_url in result["report"]["AZ"]["seed_urls"]
    assert pdf_url in result["report"]["AZ"]["top_candidate_urls"]
    assert rtf_url in result["report"]["AZ"]["top_candidate_urls"]


@pytest.mark.anyio
async def test_agentic_discovery_normalizes_raw_rtf_prefetch_content(monkeypatch: pytest.MonkeyPatch) -> None:
    rtf_url = "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeParallelWebArchiver:
        def __init__(self, **kwargs):
            pass

        async def archive_urls_parallel(self, urls):
            return [
                SimpleNamespace(
                    success=True,
                    url=rtf_url,
                    content=r"{\rtf1\ansi R18-4-101.\par Applicability. Arizona administrative code article text.}",
                    source="wayback",
                )
            ]

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            return SimpleNamespace(document=SimpleNamespace(text="", title="", html="", extraction_provenance={}))

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            return SimpleNamespace(text="", title="", html="", links=[])

    async def _fake_extract_text_from_rtf_bytes_with_processor(rtf_bytes: bytes, *, source_url: str) -> str:
        assert source_url == rtf_url
        assert b"\\rtf1" in rtf_bytes
        return "R18-4-101. Applicability. Arizona administrative code article text."

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [rtf_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(
        scraper_module,
        "_extract_text_from_rtf_bytes_with_processor",
        _fake_extract_text_from_rtf_bytes_with_processor,
    )
    monkeypatch.setattr(
        scraper_module,
        "_is_substantive_rule_text",
        lambda **kwargs: kwargs.get("url") == rtf_url and "Applicability." in str(kwargs.get("text") or ""),
    )
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
        states=["AZ"],
        max_candidates_per_state=4,
        max_fetch_per_state=1,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    statute = result["state_blocks"][0]["statutes"][0]
    assert statute["source_url"] == rtf_url
    assert statute["full_text"] == "R18-4-101. Applicability. Arizona administrative code article text."
    assert statute["section_name"] == "R18-4-101. Applicability. Arizona administrative code article text."
    assert result["report"]["AZ"]["format_counts"]["rtf"] == 1


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
async def test_agentic_discovery_utah_bootstrap_stops_after_first_successful_public_api_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    api_seed = "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules"
    search_seed = "https://adminrules.utah.gov/public/search/c/Current%20Rules"
    rule_url = "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules"
    api_calls: list[str] = []

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
            return SimpleNamespace(
                document=SimpleNamespace(
                    text="Utah rules search shell.",
                    title="Utah Administrative Rules Search",
                    html="",
                    extraction_provenance={"method": "requests_only"},
                )
            )

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
            title="R70-101. Utah Rule",
            text="R70-101. Utah administrative rule text with authority and implementation sections.",
            html="",
            links=[],
            success=True,
            method_used="utah_public_getfile_html",
            extraction_provenance={"method": "utah_public_getfile_html"},
        )

    def _fake_candidate_utah_rule_urls_from_public_api(url: str, limit: int = 24):
        api_calls.append(url)
        if url == api_seed:
            return [rule_url]
        return []

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [api_seed, search_seed])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_candidate_utah_rule_urls_from_public_api", _fake_candidate_utah_rule_urls_from_public_api)
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
    assert api_calls == [api_seed]


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
    statute = result["data"][0]["statutes"][0]
    assert statute["structured_data"]["jsonld"]["@type"] == "Legislation"
    assert statute["structured_data"]["jsonld"]["legislationType"] == "StateAdministrativeRule"
    assert statute["structured_data"]["jsonld"]["sectionNumber"] == "A1"
    assert statute["structured_data"]["jsonld"]["sourceUrl"] == "https://admincode.legislature.state.al.us/administrative-code"
    assert statute["structured_data"]["citations"]["official"] == ["AL Admin Rule A1"]
    assert result["metadata"]["agentic_recovered_states"] == ["AL"]
    assert result["metadata"]["missing_rule_states"] == []
    assert result["metadata"]["phase_timings"]["base_scrape_seconds"] >= 0.0
    assert result["metadata"]["phase_timings"]["filter_seconds"] >= 0.0
    assert result["metadata"]["phase_timings"]["agentic_discovery_seconds"] >= 0.0
    assert result["metadata"]["phase_timings"]["total_seconds"] >= result["metadata"]["phase_timings"]["agentic_discovery_seconds"]


@pytest.mark.anyio
async def test_scrape_state_admin_rules_disables_nested_state_law_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    scrape_calls = []

    async def _fake_scrape_state_laws(**kwargs):
        scrape_calls.append(dict(kwargs))
        legal_areas = kwargs.get("legal_areas")
        if legal_areas == ["administrative"]:
            return {
                "status": "success",
                "data": [
                    {
                        "state_code": "AZ",
                        "state_name": "Arizona",
                        "title": "Arizona Administrative Rules",
                        "statutes": [],
                        "rules_count": 0,
                    }
                ],
                "metadata": {"states_scraped": kwargs.get("states") or []},
            }
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "title": "Arizona Administrative Rules",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {"states_scraped": kwargs.get("states") or []},
        }

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scrape_state_admin_rules(
        states=["AZ"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=False,
        per_state_retry_attempts=3,
        per_state_timeout_seconds=90.0,
        require_substantive_rule_text=True,
    )

    assert result["status"] in {"success", "partial_success"}
    assert len(scrape_calls) == 2
    expected_delegated_timeout = float(result["metadata"]["state_laws_base_per_state_timeout_seconds"])
    for call in scrape_calls:
        assert call["per_state_retry_attempts"] == 0
        assert call["retry_zero_statute_states"] is False
        assert call["per_state_timeout_seconds"] == expected_delegated_timeout
    assert result["metadata"]["per_state_retry_attempts"] == 3
    assert result["metadata"]["state_laws_internal_retry_attempts"] == 0
    assert result["metadata"]["state_laws_internal_retry_zero_statute_states"] is False
    assert result["metadata"]["state_laws_base_per_state_timeout_seconds"] == expected_delegated_timeout
    assert result["metadata"]["state_laws_fallback_per_state_timeout_seconds"] == expected_delegated_timeout
    assert result["metadata"]["agentic_per_state_budget_seconds"] == 60.0


@pytest.mark.anyio
async def test_scrape_state_admin_rules_skips_wyoming_base_scrape_and_goes_direct_agentic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scrape_calls = []

    async def _fake_scrape_state_laws(**kwargs):
        scrape_calls.append(dict(kwargs))
        return {
            "status": "success",
            "data": [],
            "metadata": {"states_scraped": kwargs.get("states") or []},
        }

    async def _fake_agentic_discover_admin_state_blocks(**kwargs):
        assert kwargs["states"] == ["WY"]
        return {
            "status": "success",
            "state_blocks": [
                {
                    "state_code": "WY",
                    "state_name": "Wyoming",
                    "title": "Wyoming Administrative Rules",
                    "source": "Agentic web-archive discovery",
                    "source_url": "https://rules.wyo.gov/",
                    "scraped_at": "2026-03-13T00:00:00",
                    "statutes": [
                        {
                            "state_code": "WY",
                            "state_name": "Wyoming",
                            "statute_id": "WY-AGENTIC-1",
                            "code_name": "Wyoming Administrative Rules (Agentic Discovery)",
                            "section_number": "1",
                            "section_name": "Wyoming Administrative Rules Index",
                            "short_title": "Wyoming Administrative Rules Index",
                            "full_text": "Wyoming administrative rules chapter inventory and official filing links.",
                            "summary": "Wyoming administrative rules chapter inventory and official filing links.",
                            "legal_area": "administrative",
                            "source_url": "https://rules.wyo.gov/Help/Public/wyoming-administrative-rules-h.html",
                            "official_cite": "WY Admin Rule 1",
                            "structured_data": {"type": "regulation", "agentic_discovery": True},
                        }
                    ],
                    "rules_count": 1,
                    "schema_version": "1.0",
                    "normalized": True,
                }
            ],
            "kg_rows": [],
            "report": {"WY": {"rules_count": 1}},
        }

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scrape_state_admin_rules(
        states=["WY"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=True,
        require_substantive_rule_text=True,
    )

    assert scrape_calls == []
    assert result["status"] == "success"
    assert result["metadata"]["base_scrape_skipped_states"] == ["WY"]
    assert result["metadata"]["fallback_attempted_states"] is None
    assert result["metadata"]["agentic_attempted_states"] == ["WY"]
    assert result["metadata"]["agentic_recovered_states"] == ["WY"]
    assert result["data"][0]["state_code"] == "WY"
    assert result["data"][0]["rules_count"] == 1


@pytest.mark.anyio
async def test_scrape_state_admin_rules_reports_cloudflare_availability_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_scrape_state_laws(**kwargs):
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "title": "Arizona Administrative Rules",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {"states_scraped": kwargs.get("states") or []},
        }

    for env_name in (
        "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
        "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_ACCOUNT_ID",
        "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
        "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_API_TOKEN",
    ):
        monkeypatch.delenv(env_name, raising=False)

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scrape_state_admin_rules(
        states=["AZ"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=False,
        agentic_fallback_enabled=False,
        require_substantive_rule_text=True,
    )

    cloudflare = result["metadata"]["cloudflare_browser_rendering"]
    assert cloudflare["available"] is False
    assert cloudflare["status"] == "missing_credentials"
    assert cloudflare["provider"] == "cloudflare_browser_rendering"
    assert cloudflare["missing_credentials"] == ["account_id", "api_token"]


@pytest.mark.anyio
async def test_scrape_state_admin_rules_propagates_agentic_cloudflare_rate_limit_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "title": "Arizona Administrative Rules",
                    "source": "Agentic web-archive discovery",
                    "source_url": "https://rules.az.gov/",
                    "scraped_at": "2026-03-12T00:00:00",
                    "statutes": [],
                    "rules_count": 0,
                    "schema_version": "1.0",
                    "normalized": True,
                    "cloudflare_status": "rate_limited",
                    "retry_after_seconds": 180.0,
                    "retry_at_utc": "2026-03-12T00:03:00Z",
                    "retryable": True,
                    "wait_budget_exhausted": True,
                    "rate_limit_diagnostics": {"provider": "cloudflare_browser_rendering", "budget_seconds": 60},
                }
            ],
            "kg_rows": [],
            "report": {
                "AZ": {
                    "rules_count": 0,
                    "cloudflare_status": "rate_limited",
                    "retry_after_seconds": 180.0,
                    "retry_at_utc": "2026-03-12T00:03:00Z",
                    "retryable": True,
                    "wait_budget_exhausted": True,
                    "rate_limit_diagnostics": {"provider": "cloudflare_browser_rendering", "budget_seconds": 60},
                }
            },
        }

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scrape_state_admin_rules(
        states=["AZ"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=True,
        require_substantive_rule_text=True,
    )

    assert result["status"] == "rate_limited"
    assert result["metadata"]["cloudflare_status"] == "rate_limited"
    assert result["metadata"]["retry_after_seconds"] == 180.0
    assert result["metadata"]["retry_at_utc"] == "2026-03-12T00:03:00Z"
    assert result["metadata"]["retryable"] is True
    assert result["metadata"]["wait_budget_exhausted"] is True
    assert result["metadata"]["rate_limit_diagnostics"]["provider"] == "cloudflare_browser_rendering"
    assert result["metadata"]["rate_limited_states"] == ["AZ"]
    assert result["metadata"]["missing_rule_states"] == ["AZ"]


@pytest.mark.anyio
async def test_scrape_state_admin_rules_propagates_agentic_cloudflare_browser_challenge_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "title": "Arizona Administrative Rules",
                    "source": "Agentic web-archive discovery",
                    "source_url": "https://azsos.gov/rules/arizona-administrative-code",
                    "scraped_at": "2026-03-12T00:00:00",
                    "statutes": [],
                    "rules_count": 0,
                    "schema_version": "1.0",
                    "normalized": True,
                    "cloudflare_status": "browser_challenge",
                    "cloudflare_http_status": 403,
                    "cloudflare_browser_challenge_detected": True,
                    "cloudflare_error_excerpt": "Just a moment... Enable JavaScript and cookies to continue",
                    "cloudflare_record_status": "errored",
                    "cloudflare_job_status": "completed",
                }
            ],
            "kg_rows": [],
            "report": {
                "AZ": {
                    "rules_count": 0,
                    "cloudflare_status": "browser_challenge",
                    "cloudflare_http_status": 403,
                    "cloudflare_browser_challenge_detected": True,
                    "cloudflare_error_excerpt": "Just a moment... Enable JavaScript and cookies to continue",
                    "cloudflare_record_status": "errored",
                    "cloudflare_job_status": "completed",
                }
            },
        }

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scrape_state_admin_rules(
        states=["AZ"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=True,
        require_substantive_rule_text=True,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["cloudflare_status"] == "browser_challenge"
    assert result["metadata"]["cloudflare_http_status"] == 403
    assert result["metadata"]["cloudflare_browser_challenge_detected"] is True
    assert result["metadata"]["cloudflare_record_status"] == "errored"
    assert result["metadata"]["cloudflare_job_status"] == "completed"
    assert result["metadata"]["browser_challenge_states"] == ["AZ"]


@pytest.mark.anyio
async def test_scrape_state_admin_rules_ignores_benign_agentic_cloudflare_success_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                    "state_code": "IN",
                    "state_name": "Indiana",
                    "title": "Indiana Administrative Rules",
                    "source": "Agentic web-archive discovery",
                    "source_url": "https://iar.iga.in.gov/code/current",
                    "scraped_at": "2026-03-13T00:00:00",
                    "statutes": [],
                    "rules_count": 0,
                    "schema_version": "1.0",
                    "normalized": True,
                    "cloudflare_status": "success",
                    "cloudflare_http_status": 200,
                    "cloudflare_browser_challenge_detected": False,
                    "cloudflare_error_excerpt": "Indiana Register You need to enable JavaScript to run this app.",
                    "cloudflare_record_status": "completed",
                    "cloudflare_job_status": "completed",
                }
            ],
            "kg_rows": [],
            "report": {
                "IN": {
                    "rules_count": 0,
                    "cloudflare_status": "success",
                    "cloudflare_http_status": 200,
                    "cloudflare_browser_challenge_detected": False,
                    "cloudflare_error_excerpt": "Indiana Register You need to enable JavaScript to run this app.",
                    "cloudflare_record_status": "completed",
                    "cloudflare_job_status": "completed",
                }
            },
        }

    monkeypatch.setattr(scraper_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(scraper_module, "_agentic_discover_admin_state_blocks", _fake_agentic_discover_admin_state_blocks)
    monkeypatch.setattr(scraper_module, "_collect_admin_source_diagnostics", lambda states: {})

    result = await scrape_state_admin_rules(
        states=["IN"],
        output_format="json",
        include_metadata=True,
        write_jsonld=False,
        retry_zero_rule_states=True,
        agentic_fallback_enabled=True,
        require_substantive_rule_text=True,
    )

    assert result["status"] == "partial_success"
    assert result["metadata"]["cloudflare_status"] is None
    assert result["metadata"]["cloudflare_http_status"] is None
    assert result["metadata"]["cloudflare_record_status"] is None
    assert result["metadata"]["cloudflare_job_status"] is None
    assert result["metadata"]["browser_challenge_states"] is None


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

    async def _fake_discover_indiana_rule_document_urls(*, limit: int = 8) -> list[str]:
        return []

    monkeypatch.setattr(scraper_module, "_discover_indiana_rule_document_urls", _fake_discover_indiana_rule_document_urls)
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
async def test_agentic_discovery_bootstraps_wyoming_viewer_urls_from_seed_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://rules.wyo.gov/Search.aspx?mode=7"
    program_url = "https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules&PROGRAM_ID=347&MODE=7"
    viewer_url_1 = "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=16225"
    viewer_url_2 = "https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID=24261"

    search_text = (
        "Administrative Rules (Code) Agency Accountants Program Accountants Result(s) "
        "Agency Administration Program Human Resources Result(s)"
    )
    search_html = (
        "<span class='program_id hidden'>347</span>"
        "<span class='program_id hidden'>11</span>"
    )
    program_html = (
        '<a href="#" class="search-rule-link" data-whatever="16225">Chapter 1: General Provisions</a>'
        " <strong>Reference Number:</strong> 061.0001.1.10282019 "
        '<a href="#" class="search-rule-link" data-whatever="24261">Chapter 2: Examination</a>'
        " <strong>Reference Number:</strong> 061.0001.2.08082024"
    )
    viewer_text_1 = (
        "Accountants, Board of Certified Public\n"
        "Chapter 1: General Provisions\n"
        "Section 1. Authority.\n"
        "The Wyoming Board hereby adopts these rules pursuant to W.S. 16-3-103.\n"
        "Section 2. Definitions.\n"
        "Definitions apply throughout this chapter."
    )
    viewer_text_2 = (
        "Accountants, Board of Certified Public\n"
        "Chapter 2: Examination\n"
        "Section 1. Examination requirement.\n"
        "Applicants shall satisfy the examination requirements under W.S. 33-3-103.\n"
        "Section 2. Scoring.\n"
        "The board shall publish passing scores and administration requirements."
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
            assert request.url == seed_url
            document = SimpleNamespace(
                text=search_text,
                title="Administrative Rules (Code)",
                html=search_html,
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            if url == seed_url:
                return SimpleNamespace(
                    text=search_text,
                    title="Administrative Rules (Code)",
                    html=search_html,
                    links=[],
                )
            return SimpleNamespace(text="", title="", html="", links=[])

    async def _fake_scrape_wyoming_rule_detail_via_ajax(url: str):
        if url == program_url:
            return SimpleNamespace(
                url=url,
                title="Wyoming Administrative Rules Program 347",
                text="Chapter 1: General Provisions Reference Number 061.0001.1.10282019 Chapter 2: Examination Reference Number 061.0001.2.08082024",
                html=program_html,
                links=[],
                success=True,
                method_used="wyoming_rules_ajax_program",
                extraction_provenance={"method": "wyoming_rules_ajax_program"},
            )
        if url == viewer_url_1:
            return SimpleNamespace(
                url=url,
                title="Chapter 1: General Provisions - Accountants, Board of Certified Public",
                text=viewer_text_1,
                html="",
                links=[],
                success=True,
                method_used="wyoming_rules_ajax_viewer",
                extraction_provenance={"method": "wyoming_rules_ajax_viewer"},
            )
        if url == viewer_url_2:
            return SimpleNamespace(
                url=url,
                title="Chapter 2: Examination - Accountants, Board of Certified Public",
                text=viewer_text_2,
                html="",
                links=[],
                success=True,
                method_used="wyoming_rules_ajax_viewer",
                extraction_provenance={"method": "wyoming_rules_ajax_viewer"},
            )
        return None

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_scrape_wyoming_rule_detail_via_ajax", _fake_scrape_wyoming_rule_detail_via_ajax)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
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
        states=["WY"],
        max_candidates_per_state=4,
        max_fetch_per_state=2,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=300,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 2
    assert [
        statute["source_url"] for statute in result["state_blocks"][0]["statutes"]
    ] == [viewer_url_1, viewer_url_2]
    assert result["report"]["WY"]["expanded_urls"] == 2


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

    async def _fake_discover_indiana_rule_document_urls(*, limit: int = 8) -> list[str]:
        return []

    monkeypatch.setattr(scraper_module, "_discover_indiana_rule_document_urls", _fake_discover_indiana_rule_document_urls)
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
    assert [statute["source_url"] for statute in result["state_blocks"][0]["statutes"]] == [deep_url]


@pytest.mark.anyio
async def test_agentic_discovery_live_fetches_ranked_indiana_direct_detail_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://iar.iga.in.gov/code/current"
    deep_url = "https://iar.iga.in.gov/code/current/10/1.5"
    deep_text = (
        "TITLE 10 Office of Attorney General ARTICLE 1.5 authority effective section rule law "
        "Sec. 1. The commissioner may adopt rules to administer the chapter. "
        "Authority: IC 4-22-2-13; IC 4-6-2-1. Affected: IC 4-22-2; IC 4-6-1. "
        "This rule governs agency procedures, notice requirements, filing obligations, and enforcement."
    )

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeParallelWebArchiver:
        def __init__(self, **kwargs):
            pass

        async def archive_urls_parallel(self, urls):
            return []

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[SimpleNamespace(url=deep_url)])

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
            if url == deep_url:
                return SimpleNamespace(
                    text=deep_text,
                    title="Title 10, Article 1.5",
                    html="",
                    links=[],
                )
            return await super().scrape(url)

    def _fake_scraper_factory(cfg):
        preferred = list(getattr(cfg, "preferred_methods", []) or [])
        if preferred and preferred[0] == "playwright":
            return _LiveScraper(cfg)
        return _GenericScraper(cfg)

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _fake_scraper_factory)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") == deep_url)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: False)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(contracts_module, "UnifiedFetchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
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
        max_fetch_per_state=1,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert [statute["source_url"] for statute in result["state_blocks"][0]["statutes"]] == [deep_url]


@pytest.mark.anyio
async def test_agentic_discovery_ranked_indiana_direct_detail_candidates_fall_back_to_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://iar.iga.in.gov/code/current"
    deep_url = "https://iar.iga.in.gov/code/current/10/1.5"
    deep_text = (
        "TITLE 10 Office of Attorney General ARTICLE 1.5 authority effective section rule law "
        "Sec. 1. The commissioner may adopt rules to administer the chapter. "
        "Authority: IC 4-22-2-13; IC 4-6-2-1. Affected: IC 4-22-2; IC 4-6-1. "
        "This rule governs agency procedures, notice requirements, filing obligations, and enforcement."
    )

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            return {"results": []}

    class _FakeParallelWebArchiver:
        def __init__(self, **kwargs):
            pass

        async def archive_urls_parallel(self, urls):
            return []

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            return SimpleNamespace(results=[SimpleNamespace(url=deep_url)])

        def agentic_discover_and_fetch(self, **kwargs):
            return {"results": []}

        def fetch(self, request):
            if request.url == deep_url:
                document = SimpleNamespace(
                    text=deep_text,
                    title="Title 10, Article 1.5",
                    html="",
                    extraction_provenance={"method": "beautifulsoup"},
                )
            else:
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

    def _fake_scraper_factory(cfg):
        return _GenericScraper(cfg)

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(parallel_web_archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _fake_scraper_factory)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") == deep_url)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: False)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(contracts_module, "UnifiedFetchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
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
        max_fetch_per_state=1,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert [statute["source_url"] for statute in result["state_blocks"][0]["statutes"]] == [deep_url]


@pytest.mark.anyio
async def test_agentic_discovery_uses_seed_prefetch_signal_before_broad_search(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://govt.westlaw.com/calregs/Index"
    deep_url = "https://govt.westlaw.com/calregs/Document/ABC123?viewType=FullText"

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            raise AssertionError("archive search should not run once a curated seed prefetch yields an inventory signal")

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            raise AssertionError("broad search should not run once a curated seed prefetch yields an inventory signal")

        def agentic_discover_and_fetch(self, **kwargs):
            raise AssertionError("agentic discovery should not run once a curated seed prefetch yields an inventory signal")

        def fetch(self, request):
            if request.url != seed_url:
                raise AssertionError(f"unexpected prefetched URL: {request.url}")
            document = SimpleNamespace(
                text="California Code of Regulations Home Title 1. General Provisions",
                title="California Code of Regulations",
                html="<html><body>Title 1</body></html>",
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            if url == seed_url:
                return SimpleNamespace(
                    text="California Code of Regulations Home Title 1. General Provisions",
                    title="California Code of Regulations",
                    html=f"<a href='{deep_url}'>Section 1</a>",
                    links=[{"url": deep_url, "text": "Section 1"}],
                )
            if url == deep_url:
                return SimpleNamespace(
                    text="Section 1. Chapter Definitions. Authority cited: Government Code section 11342.",
                    title="Section 1",
                    html="",
                    links=[],
                )
            raise AssertionError(f"unexpected scrape URL: {url}")

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_looks_like_rule_inventory_page", lambda **kwargs: kwargs.get("url") == seed_url)
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") == deep_url)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: False)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(contracts_module, "UnifiedFetchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
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
        states=["CA"],
        max_candidates_per_state=4,
        max_fetch_per_state=1,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert [statute["source_url"] for statute in result["state_blocks"][0]["statutes"]] == [deep_url]


@pytest.mark.anyio
async def test_agentic_discovery_prioritizes_deeper_california_inventory_links(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://govt.westlaw.com/calregs/Index"
    title_urls = [
        f"https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=TITLE{i}"
        for i in range(1, 7)
    ]
    division_url = "https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=DIV1"
    chapter_url = "https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=CH1"
    article_url = "https://govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=ART1"
    deep_url = "https://govt.westlaw.com/calregs/Document/ABC123?viewType=FullText"

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            raise AssertionError("archive search should not run once California seed prefetch yields an inventory signal")

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            raise AssertionError("broad search should not run once California seed prefetch yields an inventory signal")

        def agentic_discover_and_fetch(self, **kwargs):
            raise AssertionError("deep discovery should not run for recognized California inventory hops in this regression")

        def fetch(self, request):
            if request.url != seed_url:
                raise AssertionError(f"unexpected prefetched URL: {request.url}")
            document = SimpleNamespace(
                text="California Code of Regulations Title 1. General Provisions Title 2. Administration Title 3. Food and Agriculture Title 4. Business Regulations Title 5. Education Title 7. Harbors and Navigation Title 8. Industrial Relations Title 9. Rehabilitative and Developmental Services Privacy Accessibility California Office of Administrative Law",
                title="California Code of Regulations - California Code of Regulations",
                html="",
                extraction_provenance={"method": "playwright"},
            )
            return SimpleNamespace(document=document)

    def _browse_page(link_url: str, text: str, link_text: str) -> SimpleNamespace:
        return SimpleNamespace(
            text=text,
            title="Browse - California Code of Regulations",
            html=f"<a href='{link_url}'>{link_text}</a>",
            links=[{"url": link_url, "text": link_text}],
        )

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            if url == seed_url:
                html = "".join([f"<a href='{title_url}'>Title {index}. Sample</a>" for index, title_url in enumerate(title_urls, start=1)])
                links = [{"url": title_url, "text": f"Title {index}. Sample"} for index, title_url in enumerate(title_urls, start=1)]
                return SimpleNamespace(
                    text="California Code of Regulations Title 1. General Provisions Title 2. Administration Title 3. Food and Agriculture Title 4. Business Regulations Title 5. Education Title 7. Harbors and Navigation Title 8. Industrial Relations Title 9. Rehabilitative and Developmental Services Privacy Accessibility California Office of Administrative Law",
                    title="California Code of Regulations - California Code of Regulations",
                    html=html,
                    links=links,
                )
            if url == title_urls[0]:
                return _browse_page(
                    division_url,
                    "Home Title 1. General Provisions Division 1. Office of Administrative Law Privacy Accessibility California Office of Administrative Law",
                    "Division 1. Office of Administrative Law",
                )
            if url in set(title_urls[1:]):
                return SimpleNamespace(
                    text="Home Title Sample Privacy Accessibility California Office of Administrative Law",
                    title="Browse - California Code of Regulations",
                    html="",
                    links=[],
                )
            if url == division_url:
                return _browse_page(
                    chapter_url,
                    "Home Title 1. General Provisions Division 1. Office of Administrative Law Chapter 1. Review of Proposed Regulations Privacy Accessibility California Office of Administrative Law",
                    "Chapter 1. Review of Proposed Regulations",
                )
            if url == chapter_url:
                return _browse_page(
                    article_url,
                    "Home Title 1. General Provisions Division 1. Office of Administrative Law Chapter 1. Review of Proposed Regulations Article 1. Chapter Definitions Privacy Accessibility California Office of Administrative Law",
                    "Article 1. Chapter Definitions",
                )
            if url == article_url:
                return _browse_page(
                    deep_url,
                    "Home Title 1. General Provisions Division 1. Office of Administrative Law Chapter 1. Review of Proposed Regulations Article 1. Chapter Definitions § 1. Chapter Definitions. Privacy Accessibility California Office of Administrative Law",
                    "§ 1. Chapter Definitions.",
                )
            if url == deep_url:
                return SimpleNamespace(
                    text="§ 1. Chapter Definitions. Authority cited: Government Code section 11342. Reference: Sections 11340.2 and 11342.550, Government Code.",
                    title="View Document - California Code of Regulations",
                    html="",
                    links=[],
                )
            raise AssertionError(f"unexpected scrape URL: {url}")

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(
        scraper_module,
        "_looks_like_rule_inventory_page",
        lambda **kwargs: str(kwargs.get("url") or "").startswith("https://govt.westlaw.com/calregs/") and "/Document/" not in str(kwargs.get("url") or ""),
    )
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") == deep_url)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: False)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(contracts_module, "UnifiedFetchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
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
        states=["CA"],
        max_candidates_per_state=2,
        max_fetch_per_state=1,
        max_results_per_domain=4,
        max_hops=1,
        max_pages=1,
        min_full_text_chars=100,
        require_substantive_text=True,
        fetch_concurrency=1,
        per_state_budget_seconds=60,
    )

    assert result["status"] == "success"
    assert result["state_blocks"][0]["rules_count"] == 1
    assert [statute["source_url"] for statute in result["state_blocks"][0]["statutes"]] == [deep_url]
    assert result["state_blocks"][0]["statutes"][0]["section_name"] == "§ 1. Chapter Definitions."


@pytest.mark.anyio
async def test_agentic_discovery_prefers_indiana_direct_detail_seed_before_broad_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_url = "https://iar.iga.in.gov/code/current/10/1.5"
    deep_text = (
        "TITLE 10 Office of Attorney General ARTICLE 1.5 authority effective section rule law "
        "Sec. 1. The commissioner may adopt rules to administer the chapter. "
        "Authority: IC 4-22-2-13; IC 4-6-2-1. Affected: IC 4-22-2; IC 4-6-1. "
        "This rule governs agency procedures, notice requirements, filing obligations, and enforcement."
    )

    class _Method(Enum):
        PLAYWRIGHT = "playwright"

    class _FakeLegalWebArchiveSearch:
        def __init__(self, auto_archive: bool = False, use_hf_indexes: bool = True):
            pass

        async def _search_archives_multi_domain(self, query: str, domains: list[str], max_results_per_domain: int):
            raise AssertionError("archive search should not run when a direct Indiana rule seed is available")

    class _FakeUnifiedWebArchivingAPI:
        def __init__(self, scraper=None):
            self.scraper = scraper

        def search(self, request):
            raise AssertionError("broad search should not run when a direct Indiana rule seed is available")

        def agentic_discover_and_fetch(self, **kwargs):
            raise AssertionError("agentic discovery should not run when a direct Indiana rule seed is available")

        def fetch(self, request):
            raise AssertionError("fallback fetch should not run when live direct seed scraping succeeds")

    class _FakeUnifiedWebScraper:
        def __init__(self, cfg):
            self.cfg = cfg

        async def scrape(self, url: str):
            assert url == seed_url
            return SimpleNamespace(
                text=deep_text,
                title="Title 10, Article 1.5",
                html="",
                links=[],
                method_used=_Method.PLAYWRIGHT,
            )

    monkeypatch.setattr(legal_archive_module, "LegalWebArchiveSearch", _FakeLegalWebArchiveSearch)
    monkeypatch.setattr(unified_api_module, "UnifiedWebArchivingAPI", _FakeUnifiedWebArchivingAPI)
    monkeypatch.setattr(unified_web_scraper_module, "UnifiedWebScraper", _FakeUnifiedWebScraper)
    monkeypatch.setattr(scraper_module, "_discover_indiana_rule_document_urls", lambda limit=8: asyncio.sleep(0, result=[]))
    monkeypatch.setattr(scraper_module, "_extract_seed_urls_for_state", lambda state_code, state_name: [seed_url])
    monkeypatch.setattr(scraper_module, "_template_admin_urls_for_state", lambda state_code: [])
    monkeypatch.setattr(scraper_module, "_is_substantive_rule_text", lambda **kwargs: kwargs.get("url") == seed_url)
    monkeypatch.setattr(scraper_module, "_is_relaxed_recovery_text", lambda **kwargs: False)
    monkeypatch.setattr(contracts_module, "OperationMode", SimpleNamespace(BALANCED="balanced"))
    monkeypatch.setattr(contracts_module, "UnifiedSearchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(contracts_module, "UnifiedFetchRequest", lambda **kwargs: SimpleNamespace(**kwargs))
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
    assert result["state_blocks"][0]["statutes"][0]["source_url"] == seed_url
    assert result["report"]["IN"]["source_breakdown"] == {}


# ---------------------------------------------------------------------------
# Cloudflare Browser Rendering fallback in PDF/RTF candidate scrapers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_text_via_cloudflare_crawl_returns_none_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_download_text_via_cloudflare_crawl returns None when credentials are absent."""
    monkeypatch.delenv("LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_CLOUDFLARE_API_TOKEN", raising=False)

    from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
        _download_text_via_cloudflare_crawl,
    )

    result = await _download_text_via_cloudflare_crawl("https://example.com/rules.pdf")
    assert result is None


@pytest.mark.asyncio
async def test_download_text_via_cloudflare_crawl_returns_text_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_download_text_via_cloudflare_crawl parses records and returns text dict."""
    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID", "fake-account")
    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN", "fake-token")

    _crawl_result = {
        "status": "success",
        "records": [
            {
                "url": "https://example.com/rules.pdf",
                "status": "completed",
                "markdown": "# Arizona Admin Rules\n\nSection 1: blah blah blah\n" * 10,
                "html": "<h1>Arizona Admin Rules</h1>",
            }
        ],
    }

    async def _fake_crawl(url, **kwargs):
        return _crawl_result

    import ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine as _cf_eng  # noqa: F401
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine.crawl_with_cloudflare_browser_rendering",
        _fake_crawl,
    )
    # Patch the relative import path used inside state_admin_rules_scraper
    from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as _sar
    monkeypatch.setattr(
        _sar,
        "_download_text_via_cloudflare_crawl",
        lambda url: _fake_crawl_wrapper(url),
    )

    async def _fake_crawl_wrapper(url):
        return {
            "text": _crawl_result["records"][0]["markdown"],
            "html": _crawl_result["records"][0]["html"],
            "markdown": _crawl_result["records"][0]["markdown"],
            "record_url": url,
            "cloudflare_record_status": "completed",
            "cloudflare_job_status": "success",
        }

    from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
        _download_text_via_cloudflare_crawl,
    )

    # Call the patched version directly through the module to avoid import caching
    result = await _sar._download_text_via_cloudflare_crawl("https://example.com/rules.pdf")
    # The monkeypatched version returns our fake data
    assert result is not None
    assert "text" in result
    assert len(result["text"]) > 100


@pytest.mark.asyncio
async def test_download_text_via_cloudflare_crawl_falls_back_on_challenge_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID", "fake-account")
    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN", "fake-token")

    async def _fake_crawl(url, **kwargs):
        return {
            "status": "success",
            "records": [
                {
                    "url": url,
                    "status": "completed",
                    "markdown": "",
                    "html": "<html><title>Just a moment...</title><body>Enable JavaScript and cookies</body></html>",
                }
            ],
        }

    async def _fake_bypass(url):
        return {
            "text": "Administrative Rules of Montana\n1.3.201 INTRODUCTION AND DEFINITIONS\n" * 8,
            "html": "<html><body>Administrative Rules of Montana</body></html>",
            "source": "wayback_machine",
        }

    from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as _sar

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine.crawl_with_cloudflare_browser_rendering",
        _fake_crawl,
    )
    monkeypatch.setattr(_sar, "_fetch_html_bypassing_challenge", _fake_bypass)

    result = await _sar._download_text_via_cloudflare_crawl("https://example.com/blocked")

    assert result is not None
    assert result["cloudflare_record_status"] == "bypassed"
    assert result["cloudflare_job_status"] == "wayback_machine"
    assert "Administrative Rules of Montana" in result["text"]


@pytest.mark.asyncio
async def test_scrape_pdf_candidate_uses_cloudflare_fallback_when_playwright_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When requests + cloudscraper + playwright all fail, cloudflare rendering is tried."""
    import importlib

    from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as _sar

    fake_cf_text = {
        "text": "Section 1. General Provisions.\n" * 20,
        "html": "<p>Section 1. General Provisions.</p>",
        "markdown": "Section 1. General Provisions.\n" * 20,
        "record_url": "https://apps.azsos.gov/public_services/Title_18/18-01.pdf",
        "cloudflare_record_status": "completed",
        "cloudflare_job_status": "success",
    }

    # Make requests raise an exception (simulate connection failure → response is None)
    monkeypatch.setattr(_sar, "_is_pdf_candidate_url", lambda url: True)

    import requests as _requests_mod

    def _raise(*a, **kw):
        raise ConnectionError("simulated network error")

    monkeypatch.setattr(_requests_mod, "get", _raise)
    monkeypatch.setattr(_sar, "_download_document_bytes_via_cloudscraper", lambda url: None)

    async def _fake_playwright_download(url):
        return None

    monkeypatch.setattr(_sar, "_download_document_bytes_via_playwright", _fake_playwright_download)

    async def _fake_cf_crawl(url):
        return fake_cf_text

    monkeypatch.setattr(_sar, "_download_text_via_cloudflare_crawl", _fake_cf_crawl)

    from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
        _scrape_pdf_candidate_url_with_processor,
    )

    result = await _scrape_pdf_candidate_url_with_processor(
        "https://apps.azsos.gov/public_services/Title_18/18-01.pdf"
    )
    assert result is not None
    assert result.success is True
    assert result.method_used == "pdf_processor_cloudflare_rendering"
    assert "Section 1" in result.text


@pytest.mark.asyncio
async def test_scrape_rtf_candidate_uses_cloudflare_fallback_when_playwright_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RTF candidate scraper falls back to cloudflare rendering when playwright fails."""
    from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as _sar

    fake_cf_text = {
        "text": "ARTICLE I General Rules\n" * 20,
        "html": "<p>ARTICLE I General Rules</p>",
        "markdown": "ARTICLE I General Rules\n" * 20,
        "record_url": "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
        "cloudflare_record_status": "completed",
        "cloudflare_job_status": "success",
    }

    monkeypatch.setattr(_sar, "_is_rtf_candidate_url", lambda url: True)

    import requests as _requests_mod

    def _raise_rtf(*a, **kw):
        raise ConnectionError("simulated network error")

    monkeypatch.setattr(_requests_mod, "get", _raise_rtf)
    monkeypatch.setattr(_sar, "_download_document_bytes_via_cloudscraper", lambda url: None)

    async def _fake_playwright_download(url):
        return None

    monkeypatch.setattr(_sar, "_download_document_bytes_via_playwright", _fake_playwright_download)

    async def _fake_cf_crawl(url):
        return fake_cf_text

    monkeypatch.setattr(_sar, "_download_text_via_cloudflare_crawl", _fake_cf_crawl)

    from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
        _scrape_rtf_candidate_url_with_processor,
    )

    result = await _scrape_rtf_candidate_url_with_processor(
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf"
    )
    assert result is not None
    assert result.success is True
    assert result.method_used == "rtf_processor_cloudflare_rendering"
    assert "ARTICLE I" in result.text


@pytest.mark.asyncio
async def test_scrape_pdf_candidate_cloudflare_fallback_skipped_when_text_too_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloudflare fallback is ignored when returned text is shorter than 100 chars."""
    from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as _sar

    monkeypatch.setattr(_sar, "_is_pdf_candidate_url", lambda url: True)

    import requests as _requests_mod

    def _raise_short(*a, **kw):
        raise ConnectionError("simulated network error")

    monkeypatch.setattr(_requests_mod, "get", _raise_short)
    monkeypatch.setattr(_sar, "_download_document_bytes_via_cloudscraper", lambda url: None)

    async def _fake_playwright_download(url):
        return None

    monkeypatch.setattr(_sar, "_download_document_bytes_via_playwright", _fake_playwright_download)

    async def _fake_cf_crawl(url):
        # Return text that is too short to be substantive
        return {"text": "short", "html": "", "markdown": "short"}

    monkeypatch.setattr(_sar, "_download_text_via_cloudflare_crawl", _fake_cf_crawl)

    from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
        _scrape_pdf_candidate_url_with_processor,
    )

    result = await _scrape_pdf_candidate_url_with_processor(
        "https://apps.azsos.gov/public_services/Title_18/18-01.pdf"
    )
    assert result is None
