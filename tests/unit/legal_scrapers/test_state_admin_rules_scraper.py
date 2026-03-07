from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
    _is_admin_rule_statute,
    _is_substantive_admin_statute,
)


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