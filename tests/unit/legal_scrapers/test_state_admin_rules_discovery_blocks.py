from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
    _allowed_discovery_hosts_for_state,
    _looks_like_rule_inventory_page,
    _score_candidate_url,
    _url_allowed_for_state,
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


def test_score_candidate_url_rejects_superuser_and_arkansas_noise() -> None:
    assert _score_candidate_url("https://superuser.com/questions/60006/what-is-the-purpose-of-the-www-subdomain") < 0
    assert _score_candidate_url("https://www.ark.org/arec_renewals/index.php/search/view/SA00099755") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/business-commercial-services-bcs/") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/business-commercial-services-bcs/notary-e-notary") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/academics/chinese-department") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/search/results/P950") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/search/results/eyJrZXl3b3JkcyI6ImJ1c2luZXNzIHNlYXJjaCJ9") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/uploads/Proposed_Rule_Cover_Sheet.pdf") < 0
    assert _score_candidate_url("https://sur.ly/i/apps.azlibrary.gov/") < 0
    assert _score_candidate_url("https://www.sportsbookreview.com/picks/ncaa-basketball/test") < 0
    assert _score_candidate_url("https://knowledge.workspace.google.com/") < 0
    assert _score_candidate_url("https://support.google.com/mail/?hl=en") < 0
    assert _score_candidate_url("https://www.ark.org/sos/corpfilings/index.php") < 0
    assert _score_candidate_url("https://azdirect.az.gov/library-archives-public-records") < 0
    assert _score_candidate_url("https://apps.azlibrary.gov/files/docs/test.pdf") < 0
    assert _score_candidate_url("https://azsos.gov/block/rules-faq") < 0
    assert _score_candidate_url("https://extension.arizona.edu/") < 0
    assert _score_candidate_url("https://azcu.edu/student-consumer-information/") < 0
    assert _score_candidate_url("https://www.faithiu.edu/academics/counseling-licensure/") < 0
    assert _score_candidate_url("https://arkvalleyvoice.com/colorado-secretary-of-state-issues-notice-of-election-rulemaking-amendments/") < 0
    assert _score_candidate_url("https://www.azed.gov/sites/default/files/2024/08/SOS+presentation+08-19-24.pdf") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/elections/") < 0
    assert _score_candidate_url("https://www.sos.arkansas.gov/+ELECTIONS") < 0
    assert _score_candidate_url("https://www.coloradosos.gov/pubs/newsRoom/pressReleases/2025/PR20251222ElectionRules.html") < 0
    assert _score_candidate_url("https://www.coloradosos.gov/pubs/rule_making/written_comments/2023/20230314NealMcBurnett.pdf") < 0


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


def test_allowed_discovery_hosts_do_not_admit_generic_gov_suffix() -> None:
    allowed_hosts = _allowed_discovery_hosts_for_state("AZ", "Arizona")

    assert ".gov" not in allowed_hosts


def test_url_allowed_for_state_rejects_federal_gov_noise() -> None:
    allowed_hosts = _allowed_discovery_hosts_for_state("AZ", "Arizona")

    assert _url_allowed_for_state(
        "https://www.childwelfare.gov/resources/links-state-and-tribal-child-welfare-law-and-policy-arizona/",
        allowed_hosts,
    ) is False
