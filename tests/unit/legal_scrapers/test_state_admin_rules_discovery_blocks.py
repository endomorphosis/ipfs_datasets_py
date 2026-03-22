from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import _score_candidate_url


def test_score_candidate_url_rejects_pemf_professionals_domain() -> None:
    assert _score_candidate_url("https://pemfprofessionals.com/") < 0


def test_score_candidate_url_rejects_arkansas_ucc_page() -> None:
    assert (
        _score_candidate_url(
            "https://www.sos.arkansas.gov/business-commercial-services-bcs/uniform-commercial-code-ucc/"
        )
        < 0
    )
