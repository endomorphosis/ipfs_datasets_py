from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.federal_law_scraper import (
    _extract_local_rule_documents,
    _extract_rule_links,
    _extract_rule_number,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.federal_register_scraper import (
    build_ecfr_section_url,
    build_federal_register_citation_url,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.us_code_scraper import (
    build_public_law_url,
    build_uscode_section_url,
)


def test_federal_scrapers_build_recovery_citation_urls():
    assert (
        build_uscode_section_url("42", "1983")
        == "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983"
    )
    assert build_public_law_url("117", "58") == "https://www.congress.gov/public-law/117th-congress/58"
    assert build_ecfr_section_url("29", "1601.1") == "https://www.ecfr.gov/current/title-29/section-1601.1"
    assert build_federal_register_citation_url("88", "12345") == "https://www.federalregister.gov/citation/88-FR-12345"


def test_extract_rule_links_filters_and_deduplicates():
    html = """
    <html>
      <body>
        <a href="/rules/frcp/rule_1">Rule 1</a>
        <a href="https://www.law.cornell.edu/rules/frcp/rule_2">Rule 2</a>
        <a href="/rules/frcp/rule_1">Rule 1 duplicate</a>
        <a href="/rules/fre/rule_101">Ignore wrong ruleset</a>
      </body>
    </html>
    """

    links = _extract_rule_links(html, "https://www.law.cornell.edu/rules/frcp", "/rules/frcp/rule_")

    assert links == [
        "https://www.law.cornell.edu/rules/frcp/rule_1",
        "https://www.law.cornell.edu/rules/frcp/rule_2",
    ]


def test_extract_local_rule_documents_picks_rule_like_links():
    html = """
    <html>
      <body>
        <a href="/sites/default/files/2025-01/local-rules.pdf">Local Rules (Jan 2025)</a>
        <a href="/forms/civil-cover-sheet.pdf">Civil Cover Sheet</a>
        <a href="/rules-and-orders/standing-order-1">Standing Rule Order 1</a>
      </body>
    </html>
    """

    docs = _extract_local_rule_documents(html, "https://example.uscourts.gov/rules")

    assert len(docs) == 2
    assert docs[0]["url"] == "https://example.uscourts.gov/sites/default/files/2025-01/local-rules.pdf"
    assert docs[1]["url"] == "https://example.uscourts.gov/rules-and-orders/standing-order-1"


def test_extract_rule_number_from_title_or_url():
    assert _extract_rule_number("Rule 26. Duty to Disclose", "") == "26"
    assert _extract_rule_number("No rule number in title", "https://www.law.cornell.edu/rules/frcp/rule_12") == "12"
