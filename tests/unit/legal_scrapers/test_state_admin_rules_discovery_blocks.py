from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
    _looks_like_rule_inventory_page,
    _score_candidate_url,
)


def test_score_candidate_url_rejects_pemf_professionals_domain() -> None:
    assert _score_candidate_url("https://pemfprofessionals.com/") < 0


def test_score_candidate_url_rejects_arkansas_ucc_page() -> None:
    assert (
        _score_candidate_url(
            "https://www.sos.arkansas.gov/business-commercial-services-bcs/uniform-commercial-code-ucc/"
        )
        < 0
    )


def test_score_candidate_url_rejects_colorado_non_rule_pages() -> None:
    assert _score_candidate_url("https://www.coloradosos.gov/pubs/elections/Initiatives/titleBoard/index.html") < 0
    assert _score_candidate_url("https://www.sos.state.co.us/CCR/auth/loginHome.do") < 0


def test_colorado_doc_list_is_inventory_not_substantive() -> None:
    text = """
    Code of Colorado Regulations
    Browse rules by Department and Agency
    1 CCR 103-1
    1 CCR 103-2
    1 CCR 103-3
    1 CCR 103-4
    """
    assert _looks_like_rule_inventory_page(
        text=text,
        title="Code of Colorado Regulations",
        url="https://www.sos.state.co.us/CCR/NumericalCCRDocList.do?deptID=14&agencyID=3",
    ) is True
