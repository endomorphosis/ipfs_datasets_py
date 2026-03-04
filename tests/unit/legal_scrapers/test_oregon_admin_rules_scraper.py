from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon_admin_rules import (
    OregonAdministrativeRulesScraper,
)


def test_extract_chapter_ids_from_cdx_filters_and_sorts() -> None:
    payload = [
        ["original"],
        ["https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=137"],
        ["https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=1"],
        ["https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=137"],
        ["https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=102.%E2%80%A2"],
        ["https://example.org/not-a-chapter"],
    ]

    chapter_ids = OregonAdministrativeRulesScraper.extract_chapter_ids_from_cdx(payload)

    assert chapter_ids == [1, 102, 137]


def test_extract_rule_body_and_meta_parses_fields() -> None:
    scraper = OregonAdministrativeRulesScraper(parent_scraper=object())
    lines = [
        "Notice of Proposed Rule",
        "(1) Sample body line.",
        "(2) Another body line.",
        "Statutory/Other Authority: ORS 183.335 & 183.341(4)",
        "Statutes/Other Implemented: ORS 183.335",
        "History:",
        "ODE 9-2012, f. 3-30-12, cert. ef. 4-2-12",
    ]

    parsed = scraper._extract_rule_body_and_meta(lines, "Notice of Proposed Rule")

    assert parsed["authority"] == "ORS 183.335 & 183.341(4)"
    assert parsed["implemented"] == "ORS 183.335"
    assert parsed["history_lines"] == ["ODE 9-2012, f. 3-30-12, cert. ef. 4-2-12"]
    assert "Sample body line" in parsed["body_text"]
    assert "Another body line" in parsed["body_text"]
